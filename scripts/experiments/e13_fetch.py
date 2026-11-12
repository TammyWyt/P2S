#!/usr/bin/env python3
"""E13 data: every transaction (not only DEX) in the paper's two mainnet windows, with the
fields a PHT exposes (sender, nonce, gas, fees, type) and the hidden fields used only as labels
(to, value, selector, logs). Swap logs from Uniswap V2/V3/V4 give (pool, direction, amount).
Windows: 2023 = Appendix B cache 18,748,996-18,750,000; 2026 = Sec. 6.1 window 25,245,959-25,246,958.
Resumable: one JSON per block under data/experiments/_e13/blocks/."""
import json, os, sys
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from e7_labels import rpc, label, V2, V3, V4

OUT = 'data/experiments/_e13/blocks'
os.makedirs(OUT, exist_ok=True)
WINDOWS = {'2023': range(18748996, 18750001), '2026': range(25245959, 25246959)}
SWAP = (V2, V3, V4)


def one(n):
    p = f'{OUT}/{n}.json'
    if os.path.exists(p):
        return
    h = hex(n)
    B = rpc('eth_getBlockByNumber', [h, True])
    R = {r['transactionHash']: r for r in rpc('eth_getBlockReceipts', [h])}
    txs = []
    for i, t in enumerate(B['transactions']):
        r = R[t['hash']]
        inp = t.get('input', '0x')
        swaps = [x for x in (label(l) for l in r['logs'] if l['topics'] and l['topics'][0] in SWAP) if x]
        txs.append(dict(
            i=i, h=t['hash'], ty=int(t.get('type', '0x0'), 16),
            # public at S1
            s=t['from'].lower(), nonce=int(t['nonce'], 16), gas=int(t['gas'], 16),
            maxfee=int(t.get('maxFeePerGas', t.get('gasPrice')), 16),
            tip=int(t.get('maxPriorityFeePerGas', t.get('gasPrice')), 16),
            # hidden: labels only
            to=(t.get('to') or '').lower(), value=int(t['value'], 16), sel=inp[:10], ilen=(len(inp) - 2) // 2,
            input=inp if swaps else None, st=int(r['status'], 16), gu=int(r['gasUsed'], 16),
            logs=[[l['address'].lower(), l['topics'][0] if l['topics'] else None] for l in r['logs']],
            L=swaps))
    rec = dict(n=n, bf=int(B.get('baseFeePerGas', '0x0'), 16), ts=int(B['timestamp'], 16),
               gl=int(B['gasLimit'], 16), txs=txs)
    json.dump(rec, open(p + '.tmp', 'w'))
    os.replace(p + '.tmp', p)


if __name__ == '__main__':
    blocks = [b for w in WINDOWS.values() for b in w]
    print(len(blocks), flush=True)
    with ThreadPoolExecutor(4) as ex:
        for k, _ in enumerate(ex.map(one, blocks)):
            if k % 100 == 0:
                print(k, flush=True)
    print('done', flush=True)
