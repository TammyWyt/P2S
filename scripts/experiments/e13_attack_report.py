#!/usr/bin/env python3
"""E13 part 2 report: apply the P2S fee rule to the simulated blocks, for each phi and each
slippage the blind attacker assumes, and compare with the content-visible (PoS) attacker.

Parameters follow the paper exactly: each blind leg is a planter PHT of GAS_PHT_LARGE = 200k gas
(scripts/simulation/constants.py, the planter of Table 6), F_res = phi * 200k * max(base fee, g_floor)
with g_floor = 2 gwei (Eq. fres), phi = 0.20. Base fees are each block's real one.

phi_plant uses Table 6's definition (scripts/blind_grid.py): the planter is forced to bet every
candidate, F_res is priced on the base fee alone (no floor), and phi_plant is the smallest phi at
which its mean net per bet is <= 0, found by bisection.
A bet is placed iff p * m_hat - (1 - p) * 2 F_res > 0 (expected gain of Eq. 5 for a two-leg plant).
At reveal the attacker sees the victim's opening: it opens both legs iff that beats withholding.
Opened legs pay max(F_res, gas_used * base fee) each; withheld legs forfeit F_res each.

Usage: e13_attack_report.py WINDOW TAG"""
import argparse, glob, json, collections as C
import numpy as np

ROOT = '/Users/tammy/Code/P2S/data/experiments'
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from scripts.simulation.constants import GAS_PHT_LARGE as G_PLANT   # 200k, Table 6's planter
G_FLOOR = 2e9
PHIS = (0.0, 0.05, 0.1, 0.2, 0.3, 0.5, 1.0)
RNG = np.random.default_rng(13)


def fres(phi, bf, floor=True):
    return phi * G_PLANT * (max(bf, G_FLOOR) if floor else bf) / 1e18


def block_p2s(rec, phi, sl, forced=False, floor=True):
    bf = rec['bf']
    F = fres(phi, bf, floor)
    out = dict(net=0.0, extracted=0.0, bets=0, hits=0, opened=0)
    for r in rec['p2s']:
        e = r['by_slip'].get(sl)
        if not e or (not forced and e['m_hat'] <= 0):
            continue
        p = r['p']
        if not forced and p * e['m_hat'] - (1 - p) * 2 * F <= 0:
            continue
        out['bets'] += 1
        withhold = -2 * F
        if r['correct'] and e['realized_gross'] is not None:
            out['hits'] += 1
            half = e['realized_leg_gas'] / 2 * bf / 1e18
            open_ = e['realized_gross'] - 2 * max(F, half)
            if open_ > withhold:
                out['net'] += open_
                out['opened'] += 1
                if e['victim_ok']:
                    out['extracted'] += max(e['realized_gross'], 0.0)
                continue
        out['net'] += withhold
    return out


def boot_ratio(num, den, B=1000):
    ks = list(num)
    v = []
    for _ in range(B):
        pick = RNG.choice(len(ks), len(ks))
        d = sum(den[ks[i]] for i in pick)
        v.append(sum(num[ks[i]] for i in pick) / d if d else np.nan)
    return [float(np.nanpercentile(v, 2.5)), float(np.nanpercentile(v, 97.5))]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('win')
    ap.add_argument('tag')
    A = ap.parse_args()
    recs = [json.load(open(f)) for f in sorted(glob.glob(f'{ROOT}/_e13/sim/{A.win}_{A.tag}/*.json'))]
    sk = C.Counter()
    for r in recs:
        sk.update(r['skipped'])
    pos_blk = {r['n']: sum(max(x['net'], 0.0) for x in r['pos']) for r in recs}
    E_pos = sum(pos_blk.values())
    out = dict(window=A.win, blocks=len(recs), median_base_fee_gwei=float(np.median([r['bf'] for r in recs]) / 1e9),
               pos=dict(victims_evaluated=sum(len(r['pos']) for r in recs),
                        victims_profitable=sum(x['net'] > 0 for r in recs for x in r['pos']),
                        extractable_eth=E_pos, skipped=dict(sk),
                        by_version={v: sum(max(x['net'], 0) for r in recs for x in r['pos'] if x['ver'] == v)
                                    for v in (2, 3, 4)}),
               p2s={})
    slips = sorted({s for r in recs for x in r['p2s'] for s in x['by_slip']}, key=float)
    for sl in slips:
        for phi in PHIS:
            res = {r['n']: block_p2s(r, phi, sl) for r in recs}
            tot = {k: sum(v[k] for v in res.values()) for k in ('net', 'extracted', 'bets', 'hits', 'opened')}
            share = tot['extracted'] / E_pos if E_pos else None
            ci = boot_ratio({n: res[n]['extracted'] for n in res}, pos_blk) if E_pos else None
            out['p2s'][f'slip={sl}|phi={phi}'] = dict(
                **tot, residual_share=share, residual_share_ci=ci,
                removed=(1 - share) if share is not None else None,
                hit_rate=tot['hits'] / tot['bets'] if tot['bets'] else None)
    # phi_plant, Table 6's definition: forced planter, base fee alone, mean net per bet <= 0
    def mean_net(phi, sl):
        t = [block_p2s(r, phi, sl, forced=True, floor=False) for r in recs]
        n = sum(x['bets'] for x in t)
        return sum(x['net'] for x in t) / n if n else 0.0
    out['phi_plant_table6_def'] = {}
    for sl in slips:
        if mean_net(0.0, sl) <= 0:
            v = 0.0
        else:
            lo, hi = 0.0, 1e4
            if mean_net(hi, sl) > 0:
                v = None
            else:
                while hi - lo > 1e-5 * max(1.0, lo):
                    mid = (lo + hi) / 2
                    lo, hi = (mid, hi) if mean_net(mid, sl) > 0 else (lo, mid)
                v = hi
        out['phi_plant_table6_def'][f'slip={sl}'] = v
    json.dump(out, open(f'{ROOT}/e13_attack_{A.win}_{A.tag}.json', 'w'), indent=1)
    print(json.dumps({k: v for k, v in out.items() if k != 'p2s'}, indent=1))
    print('G_PLANT', G_PLANT, 'G_FLOOR', G_FLOOR)
    for k, v in out['p2s'].items():
        if k.endswith('phi=0.2') or k.endswith('phi=0.0'):
            print(k, {a: (round(b, 4) if isinstance(b, float) else b) for a, b in v.items() if a != 'residual_share_ci'})


if __name__ == '__main__':
    main()
