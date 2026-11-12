#!/usr/bin/env python3
"""E13 sender history: the 3 days (21,600 blocks) before each window, stored compactly.
Everything here is public at S1 time for any later block (past reveals are public).
Per tx: sender, to, selector, value>0, gas limit, gas used, status, swap legs, and the
whitelisted event topics (protocol labels) the tx emitted. Resumable,
one JSON per 100-block chunk under data/experiments/_e13/hist/."""
import json, os, sys
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from e7_labels import rpc, label, V2, V3, V4

ROOT = '/Users/tammy/Code/P2S/data/experiments/_e13/hist'
os.makedirs(ROOT, exist_ok=True)
DAYS = 3
SPAN = 7200 * DAYS
STARTS = {'2023': 18748996, '2026': 25245959}
SWAP = (V2, V3, V4)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from e13_labels import TOPICS


def block(n):
    h = hex(n)
    B = rpc('eth_getBlockByNumber', [h, True])
    R = {r['transactionHash']: r for r in rpc('eth_getBlockReceipts', [h])}
    out = []
    for t in B['transactions']:
        r = R[t['hash']]
        L = [x for x in (label(l) for l in r['logs'] if l['topics'] and l['topics'][0] in SWAP) if x]
        out.append([t['from'].lower(), (t.get('to') or '').lower(), t.get('input', '0x')[:10],
                    int(int(t['value'], 16) > 0), int(t['gas'], 16), int(r['gasUsed'], 16),
                    int(r['status'], 16), L,
                    sorted({l['topics'][0] for l in r['logs'] if l['topics'] and l['topics'][0] in TOPICS})])
    return [n, int(B['timestamp'], 16), out]


def chunk(c):
    p = f'{ROOT}/{c}.json'
    if os.path.exists(p):
        return
    rows = [block(n) for n in range(c, c + 100)]
    json.dump(rows, open(p + '.tmp', 'w'))
    os.replace(p + '.tmp', p)


if __name__ == '__main__':
    chunks = [c for s in STARTS.values() for c in range(s - SPAN, s, 100)]
    print(len(chunks), 'chunks', flush=True)
    with ThreadPoolExecutor(6) as ex:
        for k, _ in enumerate(ex.map(chunk, chunks)):
            if k % 20 == 0:
                print(k, flush=True)
    print('done', flush=True)
