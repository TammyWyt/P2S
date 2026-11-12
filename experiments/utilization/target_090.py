#!/usr/bin/env python3
# formerly E15 (scripts/experiments); run from the repo root.
"""E15: if senders declare tightly enough to meet u* = 0.90, how many run out of gas?

Reuses E12's 100 sampled blocks and parent-state estimates (experiments/utilization/cache/gas_margin_blocks/).
Each block is replayed in order with eth_simulateV1 under a declaration policy:
  exact_u   : limit = ceil(used / u), i.e. every tx declared at utilization u. The sender
              is assumed to know its own mainnet gas used, so this is the fewest failures
              any declaration hitting u can give (failures come from refunds, the 63/64
              rule and same-block state).
  wallet_m  : limit = ceil(m * estimate) for txs with a parent-state estimate; txs without
              one fall back to exact_0.90.
Limits never exceed the original. A tx "fails from the tighter limit" if it succeeded on
mainnet and fails in the replay. The reservation fee is then run over the replayed block
utilizations at u* = 0.90 with the rule of stuffing_duration.py.

    source real/.env.local && python3 experiments/utilization/target_090.py
"""
import glob, json, math, os, sys
sys.path.insert(0, 'experiments/utilization'); sys.path.insert(0, '.')
from gas_margin import rpc, simulate
from scripts.simulation import stuffing_duration as sd

OUT = 'experiments/utilization/cache/target_090_blocks'; os.makedirs(OUT, exist_ok=True)
U_STAR = 0.90


def exact(u):
    return lambda r: math.ceil(r['used'] / u)


def wallet(m):
    return lambda r: math.ceil(m * r['est']) if r['est'] else math.ceil(r['used'] / 0.90)


POLICIES = {'exact_0.90': exact(0.90), 'exact_0.95': exact(0.95), 'exact_1.00': exact(1.0),
            'wallet_1.00': wallet(1.0), 'wallet_0.95': wallet(0.95), 'wallet_0.90': wallet(0.90)}


def block(d):
    p = f"{OUT}/{d['n']}.json"
    if os.path.exists(p): return json.load(open(p))
    N = d['n']; B = rpc('eth_getBlockByNumber', [hex(N), True])['result']
    assert [t['hash'] for t in B['transactions']] == [r['h'] for r in d['rows']]
    o = dict(n=N, pol={})
    for k, f in POLICIES.items():
        lim = [min(r['lim'], max(21000, f(r))) for r in d['rows']]
        try:
            o['pol'][k] = dict(lim=lim, sim=simulate(N, B, lim))
        except RuntimeError:
            try:
                o['pol'][k] = dict(lim=lim, sim=simulate(N, B, lim, nofee=True), nofee=True)
            except RuntimeError as e:
                o['pol'][k] = dict(lim=lim, sim=None, cascade=str(e)[:200])
    json.dump(o, open(p + '.tmp', 'w')); os.replace(p + '.tmp', p)
    return o


def main():
    E = sorted((json.load(open(p)) for p in glob.glob('experiments/utilization/cache/gas_margin_blocks/*.json')), key=lambda d: d['n'])
    R = []
    for i, d in enumerate(E):
        R.append(block(d)); print(i + 1, d['n'], flush=True)
    res = {}
    for k in POLICIES:
        fail = txm = used = lim = skipped = oog = 0; BU = []; why = {}
        for d, o in zip(E, R):
            q = o['pol'][k]
            if q['sim'] is None: skipped += 1; continue
            txm += len(d['rows']); bu = sum(s[1] for s in q['sim']); bl = sum(q['lim'])
            used += bu; lim += bl; BU.append(bu / bl)
            for r, s in zip(d['rows'], q['sim']):
                if r['ok'] and not s[0]:
                    fail += 1; m = (s[2] or '').lower()
                    c = 'out of gas' if 'gas' in m else 'reverted'
                    why[c] = why.get(c, 0) + 1
        f = 1.0; peak = 1.0
        for u in BU:
            f = sd.next_reservation_fee(f, 1 - u, u_target=1 - U_STAR, floor=1.0); peak = max(peak, f)
        BU.sort()
        res[k] = dict(utilization=used / lim, block_u_p10=BU[len(BU) // 10],
                      blocks_at_or_above_target=sum(u >= U_STAR for u in BU) / len(BU),
                      newly_failed=fail, newly_failed_rate=fail / txm, failure_kind=why,
                      fee_end_multiple=f, fee_peak_multiple=peak, blocks_cascade_skipped=skipped)
    out = dict(blocks=len(E), txs=sum(len(d['rows']) for d in E), u_star=U_STAR, policies=res)
    json.dump(out, open('experiments/utilization/data/target_090.json', 'w'), indent=1)
    print(json.dumps(out, indent=1))


if __name__ == '__main__':
    main()
