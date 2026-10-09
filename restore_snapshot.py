"""Restore the public data snapshot without changing an existing dashboard."""
import gzip
import hashlib
import json
from pathlib import Path
import re
import shutil
import sqlite3
import tempfile

ROOT = Path(__file__).resolve().parent

def content_hash(folder):
    result = hashlib.sha256()
    for path in sorted((p for p in folder.rglob('*') if p.is_file() and '__pycache__' not in p.parts),
                       key=lambda p:p.relative_to(folder).as_posix()):
        name = path.relative_to(folder).as_posix()
        result.update(name.encode() + b'\0' + hashlib.sha256(path.read_bytes()).digest())
    return result.hexdigest()

def restore(root=ROOT, destination=None):
    root = Path(root)
    destination = Path(destination) if destination is not None else root/'arena/data'
    if destination.exists():
        raise FileExistsError(f'{destination.name}/ already exists. Existing dashboard data was not changed.')
    snapshot = root/'snapshot'
    manifest = json.loads((snapshot/'manifest.json').read_text(encoding='utf-8'))
    agents = json.loads((snapshot/'agents.json').read_text(encoding='utf-8'))
    runs = json.loads(gzip.decompress((snapshot/'runs.json.gz').read_bytes()))
    if len(agents) != manifest['published_agents'] or len(runs) != manifest['runs']:
        raise ValueError('Snapshot record counts do not match the manifest')
    if any(r['status'] in ('queued','running') for r in runs):
        raise ValueError('Refusing to restore auto-running jobs')
    destination.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with tempfile.TemporaryDirectory(prefix='.restore-', dir=destination.parent) as staging:
        data = Path(staging)/'data'
        data.mkdir()
        for agent in agents:
            if not re.fullmatch(r'[a-f0-9]{32}', agent['id']):
                raise ValueError('Invalid agent identifier')
            source = (root/agent['source']).resolve()
            if not source.is_relative_to((root/'agents').resolve()) or source.is_symlink():
                raise ValueError('Invalid agent source path')
            if any(p.is_symlink() for p in source.rglob('*')) or content_hash(source) != agent['hash']:
                raise ValueError('Agent source hash mismatch: ' + agent['name'])
            shutil.copytree(source, data/'agents'/agent['id'], ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
        ids = {r['id'] for r in runs}
        for archive in sorted((snapshot/'history').glob('*.jsonl.gz')):
            run_id = archive.name.removesuffix('.jsonl.gz')
            if run_id not in ids or not re.fullmatch(r'[a-f0-9]{32}', run_id):
                raise ValueError('Unrecognised history archive')
            folder = data/'runs'/run_id
            folder.mkdir(parents=True, exist_ok=True)
            with gzip.open(archive, 'rt', encoding='utf-8') as stream:
                for line in stream:
                    item = json.loads(line)
                    if not re.fullmatch(r'game-\d+\.(json|log)', item['file']):
                        raise ValueError('Invalid history filename')
                    path = folder/item['file']
                    if path.exists():
                        raise ValueError('Duplicate history filename')
                    if path.suffix == '.json':
                        path.write_text(json.dumps(item['data'], ensure_ascii=False), encoding='utf-8')
                        count += 1
                    else:
                        path.write_text(item['text'], encoding='utf-8')
        if count != manifest['game_histories']:
            raise ValueError('History count does not match the manifest')
        db = sqlite3.connect(data/'arena.sqlite')
        try:
            with db:
                for table, rows in [('agents',agents),('runs',runs)]:
                    db.execute(f'CREATE TABLE {table} (id TEXT PRIMARY KEY, payload TEXT NOT NULL)')
                    db.executemany(f'INSERT INTO {table} VALUES (?, ?)', [(x['id'],json.dumps(x,ensure_ascii=False)) for x in rows])
        finally:
            db.close()
        data.rename(destination)
    return {'agents':len(agents),'runs':len(runs),'histories':count}

if __name__ == '__main__':
    try:
        print('Restored:', restore())
    except (FileExistsError, ValueError) as exc:
        raise SystemExit(str(exc))
