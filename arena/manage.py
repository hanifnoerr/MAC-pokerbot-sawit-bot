"""CLI for bulk registration and queuing through the running local dashboard."""
import argparse
import base64
import json
from pathlib import Path
from urllib.request import Request, urlopen

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', default='http://127.0.0.1:8765')
    commands = parser.add_subparsers(dest='command', required=True)
    upload = commands.add_parser('import')
    upload.add_argument('files', nargs='+', help='Python/zip paths or glob patterns')
    upload.add_argument('--prefix', default='')
    queue = commands.add_parser('run')
    queue.add_argument('--agents', nargs='+', required=True, help='Agent IDs from import output or state')
    queue.add_argument('--mode', choices=['benchmark','tournament'], default='benchmark')
    queue.add_argument('--seeds', nargs='+', default=['arena-1','arena-2','arena-3'])
    queue.add_argument('--deals', type=int, default=100)
    queue.add_argument('--parallel-games', type=int, help='Concurrent games within each round; server default is 4')
    commands.add_parser('state')
    args = parser.parse_args()
    def call(path, payload=None):
        request = Request(args.url + path, data=json.dumps(payload).encode() if payload is not None else None, headers={'Content-Type':'application/json'})
        with urlopen(request, timeout=30) as response:
            return json.load(response)
    if args.command=='import':
        import glob
        files = sorted({p for pattern in args.files for p in glob.glob(pattern)})
        if not files:
            parser.error('No matching files')
        for name in files:
            path=Path(name)
            print(json.dumps(call('/api/agents',{'name':args.prefix+path.stem,'filename':path.name,'content':base64.b64encode(path.read_bytes()).decode()})))
    elif args.command=='run':
        payload={'mode':args.mode,'agents':args.agents,'seeds':args.seeds,'deals':args.deals}
        if args.parallel_games is not None:payload['parallel_games']=args.parallel_games
        print(json.dumps(call('/api/runs',payload),indent=2))
    else:
        print(json.dumps(call('/api/state'),indent=2))

if __name__=='__main__':
    main()
