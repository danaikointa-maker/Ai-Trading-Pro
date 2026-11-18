"""Read-only comparison of MT5 gold bars with the VM100 bridge snapshot."""
import argparse
import json
import shlex
import subprocess
import time

import MetaTrader5 as mt5
from mt5_readonly_market_publisher import TIMEFRAMES, require_running_terminal


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--timeframe', choices=TIMEFRAMES, default='M5')
    args = parser.parse_args()
    require_running_terminal()
    remote = """
import json, sqlite3, time
c = sqlite3.connect('file:/home/danai/no7-ai-trading-pro-dev/storage/db/no7.sqlite3?mode=ro', uri=True)
row = c.execute('SELECT snapshot, last_seen FROM bridge_sessions WHERE account_id=?', ('mt5-bridge-demo',)).fetchone()
if not row:
    raise SystemExit('No bridge snapshot')
s = json.loads(row[0])
print(json.dumps({'rates': s.get('rates', {}).get('XAUUSD.s', {}).get('M5', []),
                  'all_rates': s.get('rates', {}).get('XAUUSD.s', {}),
                  'quote': s.get('quotes', {}).get('XAUUSD.s'), 'poll_age': time.time()-row[1]}))
"""
    result = subprocess.run(['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=5',
                             'danai@192.168.1.10', 'python3 -c ' + shlex.quote(remote)],
                            capture_output=True, text=True, timeout=15, check=True)
    bridge = json.loads(result.stdout)
    if not mt5.initialize(r'C:\Program Files\MetaTrader 5\terminal64.exe', timeout=5000):
        raise SystemExit('Could not attach to the open terminal')
    try:
        bars = mt5.copy_rates_from_pos('XAUUSD.s', getattr(mt5, TIMEFRAMES[args.timeframe]), 0, 600)
        tick = mt5.symbol_info_tick('XAUUSD.s')
        if bars is None or len(bars) < 2 or tick is None:
            raise SystemExit('Terminal bars/quote unavailable')
        terminal = {int(b['time']): b for b in bars[:-1]}
        compared = mismatches = 0
        # The snapshot's final bar was still open when it was captured. It may
        # close while SSH/IPC is running, so exclude it from a closed-bar check.
        snapshot_bars = bridge['all_rates'].get(args.timeframe, [])
        for bar in snapshot_bars[:-1]:
            observed = terminal.get(bar['t'])
            if observed is None:
                continue
            compared += 1
            mismatches += any(abs(float(observed[name])-bar[key]) > 1e-8
                              for name, key in [('open', 'o'), ('high', 'h'), ('low', 'l'), ('close', 'c')])
        print(json.dumps({'symbol': 'XAUUSD.s', 'timeframe': args.timeframe, 'closed_bars_compared': compared,
                          'ohlc_mismatches': mismatches, 'bridge_poll_age_seconds': round(bridge['poll_age'], 2),
                          'mt5_bid': tick.bid, 'bridge_bid': (bridge['quote'] or {}).get('bid'),
                          'mt5_timestamp_minus_pc_seconds': round(tick.time-time.time())}))
        if compared < 20 or mismatches or bridge['poll_age'] > 5:
            raise SystemExit('Comparison did not pass')
    finally:
        mt5.shutdown()


if __name__ == '__main__':
    main()
