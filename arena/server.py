"""Loopback dashboard with a persistent run queue and bounded parallel games."""
import argparse
import base64
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import random
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
import zipfile
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, parse_qs
from arena.scoring import points, table_sizes
from arena.export import lean_public_files

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'data'
HOUSE = ['house:call', 'house:checkfold', 'house:allin', 'house:random']
LIMIT = 20 * 1024 * 1024
LOCK = threading.RLock()
STOP = threading.Event()
CANCEL = set()
MAX_PARALLEL_GAMES = max(1, min(16, os.cpu_count() or 1))
DEFAULT_PARALLEL_GAMES = min(4, MAX_PARALLEL_GAMES)

def now():
    return datetime.now(timezone.utc).isoformat()

@contextmanager
def connect():
    db = sqlite3.connect(DATA / 'arena.sqlite', timeout=30)
    try:
        with db:
            yield db
    finally:
        db.close()

def init():
    DATA.mkdir(parents=True, exist_ok=True)
    with connect() as db:
        db.execute('CREATE TABLE IF NOT EXISTS agents (id TEXT PRIMARY KEY, payload TEXT NOT NULL)')
        db.execute('CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, payload TEXT NOT NULL)')
        for key, payload in db.execute('SELECT id,payload FROM runs').fetchall():
            run = json.loads(payload)
            if run['status'] == 'running':
                run.update(status='interrupted', error='Server stopped during this run. Queue a new run; partial results are excluded from leaderboard.')
                db.execute('UPDATE runs SET payload=? WHERE id=?', (json.dumps(run), key))

def all_rows(table):
    with connect() as db:
        return [json.loads(row[0]) for row in db.execute(f'SELECT payload FROM {table} ORDER BY rowid')]

def get(table, key):
    with connect() as db:
        row = db.execute(f'SELECT payload FROM {table} WHERE id=?', (key,)).fetchone()
    if not row:
        raise ValueError('Record not found')
    return json.loads(row[0])

def save(table, item):
    with connect() as db:
        db.execute(f'INSERT OR REPLACE INTO {table}(id,payload) VALUES (?,?)', (item['id'], json.dumps(item)))

def register(body):
    name = str(body.get('name', '')).strip()
    if not name or len(name) > 100:
        raise ValueError('Agent name must contain 1–100 characters')
    filename = str(body.get('filename', ''))
    try:
        raw = base64.b64decode(body['content'], validate=True)
    except Exception:
        raise ValueError('Invalid file encoding')
    if len(raw) > LIMIT:
        raise ValueError('Upload exceeds 20 MB')
    files = {}
    if filename.lower().endswith('.py'):
        files['main.py'] = raw
    elif filename.lower().endswith('.zip'):
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                total = 0
                for member in archive.infolist():
                    path = PurePosixPath(member.filename)
                    if member.is_dir():
                        continue
                    if path.is_absolute() or '..' in path.parts or '\\' in member.filename or ':' in member.filename or (member.external_attr >> 16) & 0o170000 == 0o120000:
                        raise ValueError('Zip contains an unsafe path or symlink')
                    if any(part.endswith(('.', ' ')) or part.split('.')[0].upper() in {'CON','PRN','AUX','NUL', *(f'COM{i}' for i in range(1,10)), *(f'LPT{i}' for i in range(1,10))} for part in path.parts):
                        raise ValueError('Zip contains an unsupported filename')
                    if str(path).casefold() in {p.casefold() for p in files}:
                        raise ValueError('Zip contains duplicate filenames')
                    total += member.file_size
                    if total > LIMIT or len(files) >= 300:
                        raise ValueError('Submission exceeds 20 MB unpacked or 300 files')
                    files[str(path)] = archive.read(member)
        except zipfile.BadZipFile:
            raise ValueError('Invalid zip archive')
    else:
        raise ValueError('Upload a .py file or .zip with main.py at its root')
    if 'main.py' not in files:
        raise ValueError('main.py must be at the zip root')
    digest = hashlib.sha256()
    for path, content in sorted(files.items()):
        digest.update(path.encode() + b'\0' + hashlib.sha256(content).digest())
    agent = {'id': uuid.uuid4().hex, 'name': name, 'hash': digest.hexdigest(), 'created': now(), 'files': len(files), 'bytes': sum(map(len, files.values()))}
    target = DATA / 'agents' / agent['id']
    for path, content in files.items():
        dest = target / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(content)
    save('agents', agent)
    return agent

def agent_archive(key):
    agent = get('agents', key)
    folder = DATA / 'agents' / key
    files = {}
    for path in sorted(folder.rglob('*')):
        if path.is_symlink():
            raise ValueError('Agent snapshot contains a symlink')
        if path.is_file():
            files[path.relative_to(folder).as_posix()] = path.read_bytes()
    digest = hashlib.sha256()
    for name, content in sorted(files.items()):
        digest.update(name.encode() + b'\0' + hashlib.sha256(content).digest())
    if digest.hexdigest() != agent['hash']:
        raise ValueError('Registered snapshot has changed; download refused')
    if 'main.py' not in files or len(files) > 300 or sum(map(len, files.values())) > LIMIT:
        raise ValueError('Snapshot exceeds submission packaging limits')
    files = lean_public_files(files)
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in sorted(files.items()):
            info = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, content)
    return stream.getvalue()

def queue_run(body):
    mode = body.get('mode')
    if mode not in ('benchmark', 'tournament'):
        raise ValueError('Unknown run mode')
    ids = body.get('agents', [])
    if not isinstance(ids, list) or not all(isinstance(x, str) for x in ids) or len(ids) != len(set(ids)):
        raise ValueError('Choose distinct agents')
    if not (1 if mode == 'benchmark' else 2) <= len(ids) <= 60:
        raise ValueError('Choose 1–60 benchmark agents or 2–60 tournament agents')
    for key in ids:
        get('agents', key)
    seeds = body.get('seeds', ['arena-1', 'arena-2', 'arena-3'])
    if not isinstance(seeds, list) or not 1 <= len(seeds) <= 20 or not all(isinstance(s, str) and 0 < len(s) <= 100 for s in seeds) or len(set(seeds)) != len(seeds):
        raise ValueError('Use 1–20 distinct non-empty seeds, up to 100 characters each')
    seeds = sorted(seeds)
    deals = body.get('deals', 100)
    if type(deals) is not int or not 1 <= deals <= 1000:
        raise ValueError('Hands per game must be an integer from 1 to 1000')
    parallel_games = body.get('parallel_games', DEFAULT_PARALLEL_GAMES)
    if type(parallel_games) is not int or not 1 <= parallel_games <= MAX_PARALLEL_GAMES:
        raise ValueError(f'Parallel games must be an integer from 1 to {MAX_PARALLEL_GAMES}')
    profile_config = {'seeds': seeds, 'deals': deals, 'opponents': HOUSE, 'engine': 'macpoker-0.1.0', 'stack':200, 'blinds':[1,2], 'bank_ms':30000, 'increment_ms':100, 'policy_seed_version':2, 'policy_seed':'arena-policy-v2', 'runner_version':3, 'parallel_games':parallel_games, 'blas_threads':1, 'clock':'wall'}
    profile = hashlib.sha256(json.dumps(profile_config, sort_keys=True).encode()).hexdigest()[:16]
    run = {'id': uuid.uuid4().hex, 'mode':mode, 'status':'queued', 'created':now(), 'progress':'Waiting in queue', 'error':None, 'profile':profile, 'profile_config':profile_config, 'config': {'agents':ids, 'seeds':seeds, 'deals':deals, 'parallel_games':parallel_games}, 'results':[], 'leaderboard':[]}
    save('runs',run)
    return run

def kill_tree(proc):
    if proc.poll() is None:
        if os.name == 'nt':
            subprocess.run(['taskkill', '/PID', str(proc.pid), '/T', '/F'], capture_output=True)
        else:
            import signal
            os.killpg(proc.pid, signal.SIGKILL)
        proc.wait(timeout=10)

class Cancelled(Exception):
    pass

def game(run, agents, seed, offset, number, abort=None):
    def cancelled():
        return STOP.is_set() or run['id'] in CANCEL or (abort is not None and abort.is_set())
    if cancelled():
        raise Cancelled()
    folder = DATA / 'runs' / run['id']
    folder.mkdir(parents=True, exist_ok=True)
    specs = []
    for agent in agents:
        if agent['id'].startswith('house:'):
            specs.append(agent['id'])
        else:
            # A fresh per-game working copy prevents agents modifying their registered snapshot.
            work = folder / f'work-{number}' / agent['id']
            shutil.copytree(DATA / 'agents' / agent['id'], work)
            specs.append(str(work / 'main.py'))
    request = folder / f'game-{number}.request.json'
    result = folder / f'game-{number}.json'
    request.write_text(json.dumps({'specs':specs, 'config':{'seats':len(agents), 'deals':run['config']['deals'], 'offset':offset, 'seed':seed, 'stack':200, 'sb':1, 'bb':2, 'base_time_ms':30000, 'increment_ms':100}}), encoding='utf-8')
    with (folder / f'game-{number}.log').open('w', encoding='utf-8') as log:
        env = os.environ.copy()
        if run.get('profile_config', {}).get('runner_version', 0) >= 3:
            for key in ('OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'OMP_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
                env[key] = '1'
        proc = subprocess.Popen([sys.executable, '-u', str(ROOT / 'game_worker.py'), str(request), str(result)], stdout=log, stderr=log, start_new_session=os.name != 'nt', env=env)
        started = time.monotonic()
        try:
            while proc.poll() is None:
                if cancelled():
                    raise Cancelled()
                if time.monotonic() - started > len(agents) * (30 + run['config']['deals'] * .1 + 4) + 60:
                    raise RuntimeError('Game worker exceeded its wall-clock watchdog. Run excluded from leaderboard.')
                time.sleep(.15)
        finally:
            kill_tree(proc)
            work_root = folder / f'work-{number}'
            if work_root.exists() and work_root.resolve().parent == folder.resolve():
                shutil.rmtree(work_root)
    if proc.returncode != 0:
        raise RuntimeError((folder / f'game-{number}.log').read_text(encoding='utf-8')[-4000:])
    data = json.loads(result.read_text(encoding='utf-8'))
    data.pop('hands')
    data['history_file'] = result.name
    return data

def play_table(run, agents, seed, round_no, table_no, counter):
    return play_tables(run, [(agents, seed, round_no, table_no)], counter)[0]


def play_tables(run, specs, counter):
    """Only this coordinator updates persisted results; workers own unique game files."""
    if STOP.is_set() or run['id'] in CANCEL:
        raise Cancelled()
    tables, jobs, completed = [], [], {}
    for agents, seed, round_no, table_no in specs:
        table = {'round':round_no, 'table':table_no, 'seed':seed,
                 'agents':[{'id':a['id'],'name':a['name']} for a in agents], 'games':[]}
        tables.append(table)
        run['results'].append(table)
        for offset in range(len(agents)):
            counter[0] += 1
            jobs.append((len(tables)-1, agents, seed, offset, counter[0]))
    if not jobs:
        return tables
    # Old queued profiles retain their serial behavior.
    limit = min(run['config'].get('parallel_games', 1), len(jobs))
    abort = threading.Event()
    futures = {}
    def publish():
        active = sum(f.running() for f in futures)
        run['activity'] = dict(parallel_games=limit, active_games=active,
            stage_completed=len(completed), stage_total=len(jobs),
            completed_games=sum(len(t['games']) for t in run['results']))
        run['progress'] = (f'Round {specs[0][2]} · {len(completed)}/{len(jobs)} games complete · '
                           f'{active} active / {limit} parallel · seed {specs[0][1]}')
        save('runs', run)
    with ThreadPoolExecutor(max_workers=limit, thread_name_prefix='arena-game') as pool:
        try:
            for ti, agents, seed, offset, number in jobs:
                futures[pool.submit(game, run, agents, seed, offset, number, abort)] = (ti, offset, number)
            publish()
            for future in as_completed(futures):
                ti, offset, number = futures[future]
                result = future.result()
                if STOP.is_set() or run['id'] in CANCEL:
                    raise Cancelled()
                completed[ti, offset] = result
                # Seat offsets and history numbering do not depend on completion order.
                tables[ti]['games'] = [completed[ti, j] for j in range(len(tables[ti]['agents']))
                                       if (ti, j) in completed]
                publish()
        except BaseException:
            abort.set()
            for future in futures:
                future.cancel()
            raise
        finally:
            # Wait for process-tree teardown before the next queued run may start.
            pool.shutdown(wait=True, cancel_futures=True)
            run['activity'] = dict(parallel_games=limit, active_games=0,
                stage_completed=len(completed), stage_total=len(jobs),
                completed_games=sum(len(t['games']) for t in run['results']))
            save('runs', run)
    for table in tables:
        totals = [sum(points(g['chips'])[i] for g in table['games']) for i in range(len(table['agents']))]
        placements = points(totals)
        table['standings'] = [{'id':a['id'],'game_points':totals[i],'placement_points':placements[i]}
                              for i,a in enumerate(table['agents'])]
    save('runs',run)
    return tables

def execute(run):
    agents = [get('agents', key) for key in run['config']['agents']]
    counter = [0]
    board = {a['id']: {'id':a['id'], 'name':a['name'], 'chips':0, 'hands':0, 'failures':0, 'sets':0, 'wins':0, 'placement_points':0, 'game_points':0, 'playoff_points':0} for a in agents}
    def accumulate(table, placement=True):
        for i,a in enumerate(table['agents']):
            if a['id'] not in board:
                continue
            row = board[a['id']]
            row['chips'] += sum(g['chips'][i] for g in table['games'])
            row['hands'] += sum(g['num_hands'] for g in table['games'])
            row['failures'] += sum(g['verdicts'][i] != 'OK' for g in table['games'])
            row['sets'] += 1
            row['wins'] += sum(g['chips'][i] for g in table['games']) == max(sum(g['chips'][j] for g in table['games']) for j in range(len(table['agents'])))
            if placement:
                row['placement_points'] += table['standings'][i]['placement_points']
                row['game_points'] += table['standings'][i]['game_points']
    for seed in run['config']['seeds']:
        if run['mode'] == 'benchmark':
            specs = [([agent] + [{'id':s,'name':s} for s in HOUSE], seed, 1, agent['name']) for agent in agents]
            for table in play_tables(run, specs, counter):
                accumulate(table)
        else:
            order = agents.copy()
            random.Random(seed).shuffle(order)
            round_points = {a['id']:0 for a in agents}
            game_points = {a['id']:0 for a in agents}
            for round_no in range(1,5):
                start = 0
                specs = []
                for table_no, size in enumerate(table_sizes(len(order)), 1):
                    specs.append((order[start:start+size], f'{seed}:round:{round_no}:table:{table_no}', round_no, table_no))
                    start += size
                for table in play_tables(run, specs, counter):
                    accumulate(table)
                    for row in table['standings']:
                        round_points[row['id']] += row['placement_points']
                        game_points[row['id']] += row['game_points']
                order.sort(key=lambda a: (-round_points[a['id']], -game_points[a['id']]))
                run['leaderboard'] = list(board.values())
                save('runs', run)
            # Pairwise head-to-head duplicate sets for groups tied across a prize position.
            for value in sorted(set(round_points.values()), reverse=True):
                tied = [a for a in agents if round_points[a['id']] == value]
                above = sum(v > value for v in round_points.values())
                if len(tied) > 1 and above < 3:
                    specs = []
                    for i, left in enumerate(tied):
                        for right in tied[i+1:]:
                            specs.append(([left,right], f'{seed}:playoff:{left["hash"]}:{right["hash"]}', 'playoff', f'{left["name"]} vs {right["name"]}'))
                    for table in play_tables(run, specs, counter):
                        accumulate(table, placement=False)
                        for row in table['standings']:
                            board[row['id']]['playoff_points'] += row['game_points']
    for row in board.values():
        row['mbb'] = row['chips'] / 2 / max(1,row['hands']) * 1000
        row['win_rate'] = row['wins'] / max(1,row['sets']) * 100
    run['leaderboard'] = sorted(board.values(), key=(lambda r: -r['mbb']) if run['mode']=='benchmark' else (lambda r: (-r['placement_points'], -r['playoff_points'])))
    for row in run['leaderboard']:
        row['rank'] = 1 + sum((other['mbb'] > row['mbb']) if run['mode']=='benchmark' else ((other['placement_points'], other['playoff_points']) > (row['placement_points'], row['playoff_points'])) for other in run['leaderboard'])
    run.update(status='completed', progress='Complete', finished=now())
    save('runs', run)

def worker():
    while not STOP.wait(.3):
        with LOCK:
            queued = [r for r in all_rows('runs') if r['status']=='queued']
            if not queued:
                continue
            run = queued[0]
            run.update(status='running', started=now())
            save('runs',run)
        try:
            execute(run)
        except Cancelled:
            run.update(status='cancelled', progress='Cancelled; partial results excluded', finished=now())
            save('runs',run)
        except Exception as exc:
            run.update(status='failed',error=str(exc),finished=now())
            save('runs',run)

def state(profile=None):
    runs = all_rows('runs')
    profiles = {}
    for run in runs:
        if run['mode']=='benchmark':
            cfg=run['config']
            profiles[run['profile']]={'id':run['profile'],'label':f'{cfg["deals"]} hands · {len(cfg["seeds"])} seeds · {cfg.get("parallel_games",1)} parallel · '+', '.join(cfg['seeds'])}
    profile = profile if profile in profiles else next(reversed(profiles), None)
    rows = {}
    for run in sorted(runs, key=lambda r:r.get('finished',r['created'])):
        if run['mode']=='benchmark' and run['profile']==profile and run['status']=='completed':
            for row in run['leaderboard']:
                rows[row['id']]={**row,'run_id':run['id']}
    summaries = [{k:v for k,v in r.items() if k!='results'} for r in reversed(runs)]
    return {'agents':all_rows('agents'),'runs':summaries,'leaderboard':sorted(rows.values(),key=lambda r:-r['mbb']),'profiles':list(profiles.values()),'profile':profile,
            'scheduler':{'default_parallel_games':DEFAULT_PARALLEL_GAMES,'max_parallel_games':MAX_PARALLEL_GAMES}}

class Handler(BaseHTTPRequestHandler):
    def send(self,status,data,ctype='application/json',download=None):
        raw = json.dumps(data).encode() if ctype=='application/json' else data
        self.send_response(status)
        self.send_header('Content-Type',ctype)
        self.send_header('Content-Length',str(len(raw)))
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        if download:
            self.send_header('Content-Disposition', f'attachment; filename="{download}"')
        self.end_headers()
        self.wfile.write(raw)

    def allowed(self):
        host=self.headers.get('Host','')
        port=self.server.server_port
        if host not in (f'127.0.0.1:{port}',f'localhost:{port}'):
            return False
        origin=self.headers.get('Origin')
        return origin is None or origin in (f'http://127.0.0.1:{port}', f'http://localhost:{port}')

    def do_GET(self):
        if not self.allowed():
            return self.send(403,{'error':'Local requests only'})
        url=urlsplit(self.path)
        try:
            if url.path=='/api/state':
                return self.send(200,state(parse_qs(url.query).get('profile',[None])[0]))
            match=re.fullmatch(r'/api/agents/([a-f0-9]{32})/download',url.path)
            if match:
                key=match[1]
                agent = get('agents', key)
                filename = re.sub(r'[^A-Za-z0-9._-]+', '-', agent.get('slug') or agent['name']).strip('.') or key
                return self.send(200,agent_archive(key),'application/zip',f'{filename}.zip')
            if re.fullmatch(r'/api/runs/[a-f0-9]{32}',url.path):
                return self.send(200,get('runs',url.path.rsplit('/',1)[-1]))
            match=re.fullmatch(r'/api/history/([a-f0-9]{32})/(game-\d+\.json)',url.path)
            if match:
                path=DATA/'runs'/match[1]/match[2]
                return self.send(200,json.loads(path.read_text(encoding='utf-8')))
            mapping={'/':('index.html','text/html; charset=utf-8'),'/style.css':('style.css','text/css; charset=utf-8'),'/app.js':('app.js','text/javascript; charset=utf-8')}
            if url.path in mapping:
                name,mime=mapping[url.path]
                return self.send(200,(ROOT/'static'/name).read_bytes(),mime)
            self.send(404,{'error':'Not found'})
        except (ValueError,FileNotFoundError) as exc:
            self.send(404,{'error':str(exc)})

    def do_POST(self):
        if not self.allowed() or self.headers.get('Content-Type','').split(';')[0]!='application/json':
            return self.send(403,{'error':'Use same-origin JSON requests'})
        try:
            length=int(self.headers.get('Content-Length','0'))
            if not 0 < length <= 29*1024*1024:
                raise ValueError('Request too large or empty')
            body=json.loads(self.rfile.read(length))
            if not isinstance(body,dict):
                raise ValueError('Expected JSON object')
            with LOCK:
                if self.path=='/api/agents':
                    return self.send(201,register(body))
                if self.path=='/api/runs':
                    return self.send(201,queue_run(body))
                match=re.fullmatch(r'/api/runs/([a-f0-9]{32})/cancel',self.path)
                if match:
                    run=get('runs',match[1])
                    if run['status']=='queued':
                        run['status']='cancelled'
                        save('runs',run)
                    elif run['status']=='running':
                        CANCEL.add(run['id'])
                    return self.send(200,{'ok':True})
            self.send(404,{'error':'Not found'})
        except (ValueError,KeyError,TypeError) as exc:
            self.send(400,{'error':str(exc)})

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--port',type=int,default=8765)
    args=parser.parse_args()
    init()
    server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler)
    thread=threading.Thread(target=worker,daemon=True)
    thread.start()
    print(f'Poker Arena: http://127.0.0.1:{args.port}',flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        STOP.set()
        thread.join(timeout=15)
        server.server_close()

if __name__=='__main__':
    main()
