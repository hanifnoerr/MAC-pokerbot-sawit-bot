import gzip
import hashlib
import json
from pathlib import Path
import re
import tempfile
import unittest
import zipfile

import restore_snapshot

ROOT = Path(__file__).resolve().parents[1]

class ReleaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.agents = json.loads((ROOT/'snapshot/agents.json').read_text(encoding='utf-8'))
        cls.manifest = json.loads((ROOT/'snapshot/manifest.json').read_text(encoding='utf-8'))
        cls.runs = json.loads(gzip.decompress((ROOT/'snapshot/runs.json.gz').read_bytes()))

    def test_registered_sources_and_archives_match(self):
        self.assertEqual(len(self.agents), 58)
        forbidden = ('agi-m1','agi-s2','agi-f4','ppo_5p','ppo_lookup','ppo_456p')
        for agent in self.agents:
            self.assertFalse(agent['name'].lower().startswith(forbidden))
            source = ROOT/agent['source']
            self.assertEqual(restore_snapshot.content_hash(source), agent['hash'])
            raw = (ROOT/agent['archive']).read_bytes()
            self.assertEqual(hashlib.sha256(raw).hexdigest(), agent['archive_sha256'])
            with zipfile.ZipFile(ROOT/agent['archive']) as z:
                files = {p.relative_to(source).as_posix():p.read_bytes() for p in source.rglob('*')
                         if p.is_file() and '__pycache__' not in p.parts}
                self.assertEqual({n:z.read(n) for n in z.namelist()}, files)
        winner = next(a for a in self.agents if a.get('leaderboard_name') == 'sawit-bot')
        raw = (ROOT/winner['submission_archive']).read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), winner['submission_sha256'])

    def test_history_counts_references_and_privacy(self):
        self.assertEqual(len(self.runs), 104)
        self.assertFalse(any(r['status'] in ('queued','running') for r in self.runs))
        paths = re.compile(rb'(?i)(?:[a-z]:[\\/]+(?:users|documents|program files)[\\/]|/(?:Users|home)/[^\s/]+/|gh[pousr]_[A-Za-z0-9_]{25,}|github_pat_[A-Za-z0-9_]{25,}|-----BEGIN (?:RSA |OPENSSH )?PRIVATE KEY-----)')
        count = 0
        available = set()
        for archive in (ROOT/'snapshot/history').glob('*.jsonl.gz'):
            rid = archive.name.removesuffix('.jsonl.gz')
            with gzip.open(archive, 'rb') as stream:
                for line in stream:
                    self.assertIsNone(paths.search(line), archive.name)
                    item = json.loads(line)
                    available.add((rid,item['file']))
                    count += int(item['file'].endswith('.json'))
        self.assertEqual(count, self.manifest['game_histories'])
        for run in self.runs:
            for table in run.get('results',[]):
                for game in table.get('games',[]):
                    if game.get('history_file'):
                        self.assertIn((run['id'],game['history_file']), available)
        self.assertIsNone(paths.search(json.dumps(self.runs).encode()))

    def test_restore_preserves_existing_data(self):
        with tempfile.TemporaryDirectory() as temp:
            dest = Path(temp)/'data'
            dest.mkdir()
            marker = dest/'keep.txt'
            marker.write_text('existing user data')
            with self.assertRaises(FileExistsError):
                restore_snapshot.restore(ROOT, dest)
            self.assertEqual(marker.read_text(), 'existing user data')

if __name__ == '__main__':
    unittest.main()
