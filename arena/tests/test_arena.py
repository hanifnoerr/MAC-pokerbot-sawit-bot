import base64
import ast
import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile
from arena import server
from arena.scoring import points, table_sizes
from arena.export import lean_public_files


class ArenaTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.previous = server.DATA
        server.DATA = Path(self.temp.name)
        server.CANCEL.clear()
        server.init()

    def tearDown(self):
        server.DATA = self.previous
        self.temp.cleanup()

    def agent(self, action='return state.call()', name='Test'):
        source = 'from macpoker import Bot\nclass Test(Bot):\n    def act(self, state):\n        ' + action + '\n'
        return server.register({'name':name,'filename':'test.py','content':base64.b64encode(source.encode()).decode()})

    def run_for(self, agents, mode='benchmark', deals=3):
        return server.queue_run({'agents':[a['id'] for a in agents], 'seeds':['test-fixed'], 'mode':mode, 'deals':deals})

    def test_scoring_and_partitioning(self):
        self.assertEqual(points([10,8,8,4,0]), [5,3.5,3.5,2,1])
        self.assertEqual(points([0,0]), [1.5,1.5])
        for n in range(2,61):
            sizes=table_sizes(n)
            self.assertEqual(sum(sizes),n)
            self.assertTrue(all(2<=x<=9 for x in sizes))
            if n>=8:
                self.assertTrue(all(4<=x<=6 for x in sizes))

    def test_public_export_keeps_licences(self):
        files = {'main.py': b'# Source attribution\nvalue = 1\n', 'PUBLIC_BASELINES.md': b'Sources', 'LICENSE': b'Licence notice'}
        self.assertEqual(lean_public_files(files), files)

    def test_download_exact_snapshot(self):
        stream=io.BytesIO()
        with zipfile.ZipFile(stream,'w') as z:
            z.writestr('main.py','from helper import value\n')
            z.writestr('helper.py','value = 1\n')
            z.writestr('LICENSE','test license')
        agent=server.register({'name':'ZIP test','filename':'a.zip','content':base64.b64encode(stream.getvalue()).decode()})
        raw=server.agent_archive(agent['id'])
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            self.assertEqual(set(z.namelist()),{'main.py','helper.py','LICENSE'})
            self.assertEqual(z.read('helper.py'),b'value = 1\n')
        self.assertEqual(raw,server.agent_archive(agent['id']))
        again=server.register({'name':'Export roundtrip','filename':'a.zip','content':base64.b64encode(raw).decode()})
        self.assertEqual(agent['hash'],again['hash'])
        (server.DATA/'agents'/agent['id']/'helper.py').write_text('changed')
        with self.assertRaises(ValueError):
            server.agent_archive(agent['id'])



    def test_upload_limits_and_traversal(self):
        for path in ['../main.py','C:/main.py','main.py/../../bad','CON.py','main.py.']:
            stream=io.BytesIO()
            with zipfile.ZipFile(stream,'w') as z:
                z.writestr(path,'x')
            with self.assertRaises(ValueError):
                server.register({'name':'x','filename':'a.zip','content':base64.b64encode(stream.getvalue()).decode()})
        stream=io.BytesIO()
        with zipfile.ZipFile(stream,'w') as z:
            z.writestr('main.py','x')
            z.writestr('MAIN.py','y')
        with self.assertRaises(ValueError):
            server.register({'name':'x','filename':'a.zip','content':base64.b64encode(stream.getvalue()).decode()})

    def test_real_engine_repeatability_and_profile_isolation(self):
        agent=self.agent()
        run=self.run_for([agent])
        server.execute(run)
        games=run['results'][0]['games']
        self.assertEqual(len(games),5)
        self.assertEqual(run['leaderboard'][0]['hands'],15)
        for g in games:
            self.assertEqual(sum(g['chips']),0)
            self.assertEqual(g['verdicts'],['OK']*5)
            self.assertEqual(g['policy_seed_version'],2)
            self.assertEqual(len(g['runtime']),5)
            self.assertTrue(all(m['remaining_bank_ms']>0 for m in g['runtime']))
        self.assertEqual(run['profile_config']['policy_seed_version'],2)
        again=self.run_for([agent])
        server.execute(again)
        self.assertEqual([g['chips'] for g in games],[g['chips'] for g in again['results'][0]['games']])
        board=server.state(run['profile'])['leaderboard']
        self.assertEqual(len(board),1)
        self.assertEqual(board[0]['hands'],15)
        other=self.run_for([agent],deals=4)
        self.assertNotEqual(other['profile'],run['profile'])
        self.assertEqual(server.state(other['profile'])['leaderboard'],[])

    def test_crashed_bot_scored_not_dropped(self):
        bad=self.agent('raise RuntimeError("test crash")')
        run=self.run_for([bad])
        server.execute(run)
        self.assertEqual(run['status'],'completed')
        self.assertEqual(run['leaderboard'][0]['failures'],5)
        self.assertTrue(all(g['verdicts'][0]=='RTE' for g in run['results'][0]['games']))

    def test_tournament_four_rounds_and_tie_playoff(self):
        agents=[self.agent(name=str(i)) for i in range(2)]
        run=self.run_for(agents,mode='tournament',deals=2)
        server.execute(run)
        self.assertEqual([t['round'] for t in run['results'][:4]],[1,2,3,4])
        self.assertEqual(run['results'][-1]['round'],'playoff')
        self.assertEqual([r['placement_points'] for r in run['leaderboard']],[6,6])

    def test_cancelled_and_interrupted_excluded(self):
        run=self.run_for([self.agent()])
        server.CANCEL.add(run['id'])
        with self.assertRaises(server.Cancelled):
            server.execute(run)
        run['status']='running'
        server.save('runs',run)
        server.init()
        self.assertEqual(server.get('runs',run['id'])['status'],'interrupted')
        self.assertEqual(server.state()['leaderboard'],[])

if __name__=='__main__':
    unittest.main()
