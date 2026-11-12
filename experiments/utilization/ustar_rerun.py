#!/usr/bin/env python3
# formerly E14 (scripts/experiments); run from the repo root.
"""E14: rerun every u*-dependent result at u* = 0.60 (paper: 0.90) without touching the
paper's data. Patches the target into stuffing_duration / stuffing_reveal_gap, uses the
101-point executed-fraction grid everywhere (the optimum moves to r ~ u*, which the
paper's coarse grid misses), and writes to experiments/utilization/data/ustar_NNN/ and figures/ustar_NNN/.

Honest side: the reservation-fee rule run over (a) the 999 mainnet blocks as declared
and (b) E12/E15's replayed blocks under each declaration policy.

    python3 experiments/utilization/ustar_rerun.py [u_star]
"""
import glob, json, os, sys
sys.path.insert(0, '.')
import numpy as np
from scripts.simulation import stuffing_duration as sd
from scripts.simulation import stuffing_reveal_gap as srg
from scripts.simulation.environment import BASE_FEE_FLOOR, median_base_fee
import plots.plot_stuffing_duration as psd

U_STAR = float(sys.argv[1]) if len(sys.argv) > 1 else 0.60
TAG = f"ustar_{round(U_STAR * 100):03d}"
OUT = f'experiments/utilization/data/{TAG}'; FIG = f'experiments/utilization/figures/{TAG}'
os.makedirs(OUT, exist_ok=True); os.makedirs(FIG, exist_ok=True)

# the code's target is the UNEXECUTED fraction 1 - u*
sd.U_TARGET = srg.U_TARGET = 1 - U_STAR
sd.next_reservation_fee.__defaults__ = (1 - U_STAR, BASE_FEE_FLOOR)
sd.ADAPTIVE_R_GRID = sd.R_GRID_FINE
bf0 = median_base_fee()
sd.ADAPTIVE_R_WORST = max(sd.R_GRID_FINE, key=lambda r: sd.simulate_adaptive(1000., r, bf0=bf0))

dur = sd.run(); json.dump(dur, open(f'{OUT}/stuffing_duration.json', 'w'), indent=2)
gap = srg.run(); gap['r_grid_note'] = 'paper grid; worst case over fine grid in stuffing_duration.json'
json.dump(gap, open(f'{OUT}/stuffing_reveal_gap.json', 'w'), indent=2)
psd.FIGURES_DIR = FIG; psd.run = lambda: dur; psd.main()


def fee_path(us):
    f = peak = 1.0
    for u in us:
        f = sd.next_reservation_fee(f, 1 - u); peak = max(peak, f)
    return dict(end=f, peak=peak)


c = json.load(open('data/revert_receipts_cache.json'))
ks = sorted((k for k in c if k.isdigit()), key=int)
raw = [sum(t['gas_used'] for t in c[k]['transactions']) / sum(t['gas_limit'] for t in c[k]['transactions'])
       for k in ks if sum(t['gas_limit'] for t in c[k]['transactions'])]
honest = {'mainnet_as_declared_999': fee_path(raw)}
E = {d['n']: d for d in (json.load(open(p)) for p in glob.glob('experiments/utilization/cache/gas_margin_blocks/*.json'))}
for m in ('1.0', '1.1', '1.2', '1.3', '1.5', '2.0'):
    us = [sum(s[1] for s in E[n]['margins'][m]['sim']) / sum(E[n]['margins'][m]['lim'])
          for n in sorted(E) if E[n]['margins'][m]['sim'] is not None]
    honest[f'e12_wallet_x{m}'] = dict(fee_path(us), u_mean=float(np.mean(us)), u_p10=float(np.quantile(us, .1)))
T = {o['n']: o for o in (json.load(open(p)) for p in glob.glob('experiments/utilization/cache/target_090_blocks/*.json'))}
for k in ('exact_0.90', 'wallet_1.00'):
    us = [sum(s[1] for s in T[n]['pol'][k]['sim']) / sum(T[n]['pol'][k]['lim'])
          for n in sorted(T) if T[n]['pol'][k]['sim'] is not None]
    honest[f'e15_{k}'] = dict(fee_path(us), u_mean=float(np.mean(us)))

base = json.load(open('data/stuffing_duration.json'))
B = dur['budgets_eth']; i10, i100 = (min(range(len(B)), key=lambda j: abs(B[j] - b)) for b in (10, 100))
summary = dict(
    u_star=U_STAR, worst_executed_fraction_1000eth=sd.ADAPTIVE_R_WORST,
    blocks_at={str(b): {reg: dur['blocks_sustained'][reg][i] for reg in dur['blocks_sustained']}
               for b, i in (('10', i10), ('100', i100), ('1000', -1))},
    paper_u090_blocks_at={str(b): {reg: base['blocks_sustained'][reg][i] for reg in base['blocks_sustained']}
                          for b, i in (('10', i10), ('100', i100), ('1000', -1))},
    slope_sweep=dur['slope_sweep'], paper_u090_slope_sweep=base['slope_sweep'],
    phi_sweep=dur['phi_sweep_static'], paper_u090_phi_sweep=base['phi_sweep_static'],
    honest_fee=honest)
json.dump(summary, open(f'{OUT}/summary.json', 'w'), indent=1)
print(json.dumps(summary, indent=1))
