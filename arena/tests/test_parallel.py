import base64
import copy
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from arena import server


class ParallelTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.previous=server.DATA
        server.DATA=Path(self.temp.name)
        server.CANCEL.clear();server.STOP.clear();server.init()

    def tearDown(self):
        server.DATA=self.previous
        server.CANCEL.clear();server.STOP.clear()
        self.temp.cleanup()

    def agents(self,n,source=None):
        source=source or 'from macpoker import Bot\nclass Test(Bot):\n def act(self,s): return s.call() if s.to_call else s.check()\n'
        return [server.register(dict(name=f'Test {i}',filename='main.py',content=base64.b64encode(source.encode()).decode())) for i in range(n)]

    def run_for(self,agents,parallel,mode='tournament',deals=2):
        return server.queue_run(dict(mode=mode,agents=[a['id'] for a in agents],seeds=['parallel-fixed'],deals=deals,parallel_games=parallel))

    def test_validation_and_profile_isolation(self):
        agents=self.agents(2)
        for value in (0,-1,True,1.5,'4',None,server.MAX_PARALLEL_GAMES+1):
            with self.assertRaises(ValueError):self.run_for(agents,value)
        serial=self.run_for(agents,1);parallel=self.run_for(agents,2)
        self.assertNotEqual(serial['profile'],parallel['profile'])
        self.assertEqual(parallel['profile_config']['parallel_games'],2)
        self.assertEqual(parallel['profile_config']['clock'],'wall')

    def test_actual_sdk_serial_parallel_results_and_histories(self):
        agents=self.agents(2)
        runs=[self.run_for(agents,k) for k in (1,3)]
        for run in runs:server.execute(run)
        self.assertEqual(runs[0]['leaderboard'],runs[1]['leaderboard'])
        for a,b in zip(runs[0]['results'],runs[1]['results']):
            self.assertEqual(a['round'],b['round'])
            self.assertEqual(a['agents'],b['agents'])
            self.assertEqual(a['standings'],b['standings'])
            for x,y in zip(a['games'],b['games']):
                self.assertEqual(x['chips'],y['chips'])
                self.assertEqual(x['verdicts'],y['verdicts'])
                import json
                hx=json.loads((server.DATA/'runs'/runs[0]['id']/x['history_file']).read_text())['hands']
                hy=json.loads((server.DATA/'runs'/runs[1]['id']/y['history_file']).read_text())['hands']
                self.assertEqual(hx,hy)
        self.assertFalse(list((server.DATA/'runs').glob('*/work-*')))

    def test_round_barrier_bounded_concurrency_and_order(self):
        agents=self.agents(8)
        run=self.run_for(agents,3)
        active=peak=0;lock=threading.Lock();ended={};seen=[]
        def fake(run,agents,seed,offset,number,abort=None):
            nonlocal active,peak
            with lock:
                active+=1;peak=max(peak,active);seen.append(number)
                if ':round:' in seed:
                    round_no=int(seed.split(':round:')[1].split(':')[0])
                    if round_no>1:self.assertEqual(ended.get(round_no-1),8)
                else:round_no=None
            time.sleep(.025*(len(agents)-offset))
            with lock:
                active-=1
                if round_no:ended[round_no]=ended.get(round_no,0)+1
            return dict(chips=[i-(len(agents)-1)/2 for i in range(len(agents))],
                verdicts=['OK']*len(agents),num_hands=2,history_file=f'game-{number}.json',offset_test=offset)
        with patch.object(server,'game',side_effect=fake):server.execute(run)
        self.assertEqual(peak,3);self.assertEqual(active,0)
        self.assertEqual(len(seen),len(set(seen)))
        self.assertEqual(ended,{1:8,2:8,3:8,4:8})
        for t in run['results']:
            self.assertEqual([g['offset_test'] for g in t['games']],list(range(len(t['agents']))))
        self.assertEqual(run['activity']['active_games'],0)

    def test_failure_aborts_siblings_before_returning(self):
        agents=self.agents(5);run=self.run_for(agents,3)
        barrier=threading.Barrier(3);active=0;lock=threading.Lock();stopped=[]
        def fake(run,agents,seed,offset,number,abort=None):
            nonlocal active
            with lock:active+=1
            try:
                if number<=3:barrier.wait(timeout=3)
                if number==1:raise RuntimeError('worker failed')
                self.assertTrue(abort.wait(3))
                stopped.append(number)
                raise server.Cancelled()
            finally:
                with lock:active-=1
        with patch.object(server,'game',side_effect=fake):
            with self.assertRaisesRegex(RuntimeError,'worker failed'):server.execute(run)
        self.assertEqual(active,0);self.assertGreaterEqual(len(stopped),2)
        self.assertNotEqual(run['status'],'completed')
        self.assertEqual(run['activity']['active_games'],0)

    def test_cancel_kills_running_game_trees_and_cleans_work(self):
        source='import time\nfrom macpoker import Bot\nclass Slow(Bot):\n def act(self,s):\n  time.sleep(20)\n  return s.check()\n'
        agents=self.agents(2,source);run=self.run_for(agents,2)
        errors=[]
        def execute():
            try:server.execute(run)
            except BaseException as e:errors.append(e)
        t=threading.Thread(target=execute);t.start()
        folder=server.DATA/'runs'/run['id'];deadline=time.monotonic()+10
        while len(list(folder.glob('game-*.log')))<2 and t.is_alive() and time.monotonic()<deadline:
            time.sleep(.03)
        server.CANCEL.add(run['id']);t.join(timeout=10)
        self.assertFalse(t.is_alive())
        self.assertTrue(errors and isinstance(errors[0],server.Cancelled),errors)
        self.assertFalse(list(folder.glob('work-*')))
        self.assertEqual(run['activity']['active_games'],0)


if __name__=='__main__':unittest.main()
