"""One official-engine game. Run outside the web server process."""
import json
from pathlib import Path
import sys
import os
import ctypes
from macpoker.match import MatchConfig, MatchRunner
from macpoker.transport import SubprocessTransport

POLICY_SEED_VERSION = 2

class MeasuredTransport(SubprocessTransport):
    def __init__(self, cmd):
        super().__init__(cmd)
        self.timings_ms = []
        self.min_bank_ms = 30000
        self.peak_memory_bytes = None

    def act(self, view, timeout_ms):
        self.min_bank_ms = min(self.min_bank_ms, timeout_ms)
        action, elapsed = super().act(view, timeout_ms)
        self.timings_ms.append(elapsed)
        if os.name == 'nt' and self.proc:
            class Counters(ctypes.Structure):
                _fields_ = [('cb', ctypes.c_ulong), ('PageFaultCount', ctypes.c_ulong)] + [
                    (name, ctypes.c_size_t) for name in ['PeakWorkingSetSize', 'WorkingSetSize',
                    'QuotaPeakPagedPoolUsage', 'QuotaPagedPoolUsage', 'QuotaPeakNonPagedPoolUsage',
                    'QuotaNonPagedPoolUsage', 'PagefileUsage', 'PeakPagefileUsage']]
            counters = Counters()
            counters.cb = ctypes.sizeof(counters)
            get_memory = ctypes.windll.psapi.GetProcessMemoryInfo
            get_memory.argtypes = [ctypes.c_void_p, ctypes.POINTER(Counters), ctypes.c_ulong]
            if get_memory(int(self.proc._handle), ctypes.byref(counters), counters.cb):
                self.peak_memory_bytes = max(self.peak_memory_bytes or 0, counters.PeakWorkingSetSize)
        return action, elapsed

    def measurements(self):
        times = sorted(self.timings_ms)
        return dict(decisions=len(times), total_ms=sum(times), max_ms=max(times, default=0),
                    p99_ms=times[min(len(times)-1, int(.99*len(times)))] if times else None,
                    min_bank_ms=self.min_bank_ms, peak_working_set_bytes=self.peak_memory_bytes)

def policy_seeds(request):
    # Common policy randomness across paired deals, independent of deck seeds.
    key = request.get('policy_seed', 'arena-policy-v2')
    return [f'{key}:offset:{request["config"].get("offset", 0)}:seat:{i}'
            for i in range(len(request['specs']))]

def main():
    request = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
    cfg = MatchConfig(**request['config'])
    transports = [MeasuredTransport([sys.executable, '-u', str(Path(__file__).with_name('bot_runner.py')), spec, seed]) for spec, seed in zip(request['specs'], policy_seeds(request))]
    try:
        runner = MatchRunner(cfg, transports)
        result = runner.run()
        data = {**result.to_dict(), 'hands': result.hands, 'logs': [t.stderr_tail() for t in transports], 'policy_seed_version': POLICY_SEED_VERSION,
                'runtime': [{**t.measurements(), 'remaining_bank_ms': bank} for t, bank in zip(transports, runner.banks_ms)]}
        Path(sys.argv[2]).write_text(json.dumps(data), encoding='utf-8')
    finally:
        for transport in transports:
            transport.close()

if __name__ == '__main__':
    main()
