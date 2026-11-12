#!/usr/bin/env python3
# formerly E12 (scripts/experiments); run from the repo root.
"""E12: can senders declare tighter gas limits, and how many would run out of gas?

For each sampled block N of the 999-block window (Sec. 6), every transaction gets a
wallet estimate W = eth_estimateGas against the state after block N-1, which is what a
P2S sender knows when it commits (the rest of its block is hidden). The whole block is
then replayed in order with eth_simulateV1, each limit set to min(original, ceil(m*W)),
for several margins m. A tx "fails from the tighter limit" if it succeeded on mainnet
and fails in the replay. Utilization = replayed gas used / declared gas.

Txs whose estimate errors at the parent state (the wallet cannot estimate) keep their
original limit. A control replay with the original limits must reproduce the receipts.
Needs P2S_ARCHIVE_RPC (eth_estimateGas at historical blocks + eth_simulateV1).

    source real/.env.local && python3 experiments/utilization/gas_margin.py [n_blocks]
"""
import json, math, os, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor

U = os.environ['P2S_ARCHIVE_RPC']
OUT = 'experiments/utilization/cache/gas_margin_blocks'; os.makedirs(OUT, exist_ok=True)
MARGINS = (1.0, 1.1, 1.2, 1.3, 1.5, 2.0)
FIRST, LAST = 25245959, 25246958          # the 999-block window behind u = 0.437
NB = int(sys.argv[1]) if len(sys.argv) > 1 else 100


def rpc(m, p, to=180):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": m, "params": p})
    for t in range(12):
        o = subprocess.run(['curl', '-s', '-m', str(to), '-H', 'Content-Type: application/json',
                            '-d', '@-', U], input=body, capture_output=True, text=True).stdout
        try:
            d = json.loads(o)
        except Exception:
            time.sleep(min(60, 3 * 2 ** t)); continue
        if 'error' in d and d['error'].get('code') in (-32005, -32603, 429, -32000) and 'revert' not in str(d['error']):
            time.sleep(2 + 2 * t); continue
        return d
    raise RuntimeError((m, o[:200]))


def call(t, gas=None):
    c = {k: t[k] for k in ('from', 'input', 'value', 'nonce') if k in t}
    if t.get('to'): c['to'] = t['to']
    if gas: c['gas'] = hex(gas)
    for k in ('accessList', 'authorizationList', 'blobVersionedHashes', 'maxFeePerBlobGas'):
        if t.get(k): c[k] = t[k]
    return c


def fees(c, t):
    if 'maxFeePerGas' in t:
        c['maxFeePerGas'] = t['maxFeePerGas']; c['maxPriorityFeePerGas'] = t['maxPriorityFeePerGas']
    else:
        c['gasPrice'] = t['gasPrice']
    return c


def simulate(N, B, limits, nofee=False):
    bo = {"number": hex(N), "time": B['timestamp'], "baseFeePerGas": B['baseFeePerGas'],
          "feeRecipient": B['miner'], "prevRandao": B['mixHash'], "gasLimit": B['gasLimit']}
    calls = [call(t, g) if nofee else fees(call(t, g), t) for t, g in zip(B['transactions'], limits)]
    d = rpc('eth_simulateV1', [{"blockStateCalls": [{"blockOverrides": bo, "calls": calls}],
                                "validation": False}, hex(N - 1)])
    if 'error' in d: raise RuntimeError(d['error'])
    return [(c['status'] == '0x1', int(c['gasUsed'], 16), (c.get('error') or {}).get('message'))
            for c in d['result'][0]['calls']]


def estimate(N, t):
    # no fee fields: geth would otherwise cap the estimate by the sender's balance
    d = rpc('eth_estimateGas', [call(t), hex(N - 1)])
    return int(d['result'], 16) if 'result' in d else None


def block(N):
    p = f'{OUT}/{N}.json'
    if os.path.exists(p): return json.load(open(p))
    B = rpc('eth_getBlockByNumber', [hex(N), True])['result']
    R = rpc('eth_getBlockReceipts', [hex(N)])['result']
    T = B['transactions']
    with ThreadPoolExecutor(4) as x:
        W = list(x.map(lambda t: estimate(N, t), T))
    orig = [int(t['gas'], 16) for t in T]
    ctrl = simulate(N, B, orig)
    ok = sum(c[0] == (r['status'] == '0x1') and c[1] == int(r['gasUsed'], 16) for c, r in zip(ctrl, R))
    out = dict(n=N, txs=len(T), control_match=ok,
               rows=[dict(h=t['hash'], lim=o, used=int(r['gasUsed'], 16), ok=r['status'] == '0x1', est=w)
                     for t, o, r, w in zip(T, orig, R, W)], margins={})
    for m in MARGINS:
        lim = [o if w is None else min(o, math.ceil(m * w)) for o, w in zip(orig, W)]
        try:
            out['margins'][str(m)] = dict(lim=lim, sim=simulate(N, B, lim))
        except RuntimeError as e:          # a tightened tx failed and starved a later sender
            try:
                out['margins'][str(m)] = dict(lim=lim, sim=simulate(N, B, lim, nofee=True), nofee=True)
            except RuntimeError:
                out['margins'][str(m)] = dict(lim=lim, sim=None, cascade=str(e)[:200])
    json.dump(out, open(p + '.tmp', 'w')); os.replace(p + '.tmp', p)
    return out


def main():
    step = (LAST - FIRST) / NB
    blocks = [FIRST + int(i * step) for i in range(NB)]
    D = []
    for i, N in enumerate(blocks):
        D.append(block(N)); print(i + 1, N, D[-1]['txs'], 'control', D[-1]['control_match'], flush=True)
    txs = sum(d['txs'] for d in D); ctrl = sum(d['control_match'] for d in D)
    rows = [r for d in D for r in d['rows']]
    no_est = sum(r['est'] is None for r in rows)
    base_used = sum(r['used'] for r in rows); base_lim = sum(r['lim'] for r in rows)
    res = {}
    for m in MARGINS:
        k = str(m); fail = tight = used = lim = 0; failed_gas = 0; per_block = []; fail_oog = 0
        skipped = 0; txm = 0
        for d in D:
            if d['margins'][k]['sim'] is None:
                skipped += 1; continue
            bu = bl = 0; txm += d['txs']
            for r, l, s in zip(d['rows'], d['margins'][k]['lim'], d['margins'][k]['sim']):
                used += s[1]; lim += l; bu += s[1]; bl += l
                if l < r['lim']: tight += 1
                if r['ok'] and not s[0]:
                    fail += 1; failed_gas += r['used']
                    fail_oog += bool(s[2] and 'gas' in s[2].lower())
            per_block.append(bu / bl)
        per_block.sort()
        res[k] = dict(utilization=used / lim, block_u_p10=per_block[len(per_block) // 10],
                      txs_tightened=tight / txm, newly_failed=fail, newly_failed_rate=fail / txm,
                      newly_failed_out_of_gas=fail_oog, blocks_cascade_skipped=skipped,
                      blocks_replayed_without_fees=sum(bool(d['margins'][k].get('nofee')) for d in D))
    out = dict(blocks=len(D), txs=txs, control_exact=ctrl, no_estimate=no_est,
               baseline_utilization=base_used / base_lim, margins=res)
    json.dump(out, open('experiments/utilization/data/gas_margin.json', 'w'), indent=1)
    print(json.dumps(out, indent=1))


if __name__ == '__main__':
    main()
