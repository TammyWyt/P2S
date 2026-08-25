#!/usr/bin/env python3
"""How much of blind planting's measured profitability is an artifact of its
payoff model?

BlindPlanterBot.act() realizes its gain from AMMPool.sandwich_profit(), which
ignores its trade argument and draws from the SANDWICH distribution
(MEV_MU/MEV_SIG, mean ~0.030 ETH). But P2S removes sandwiching structurally: a
plant's position is fixed in S_1 before its sender knows anything, so it cannot
be placed adjacent to a victim. Crediting it with sandwich-scale profit is
therefore generous to the attacker, and constants.py says as much:

    "Blind planters cannot pick the best opportunity, so they draw the worse of
     two such samples."

That intent is documented and never wired in: BLIND_MU/BLIND_SIG exist and are
used only by e_net (the rationality gate), never by act() (the realized payoff).
This script re-runs the deterrence grid under each candidate payoff model and
reports what changes.

Models
  sandwich        as shipped: sample_mev_gain()                      [E ~ 0.030]
  worse_of_two    the documented intent: min of two sandwich draws
  blind_lognormal the parameter pair that already exists: LN(BLIND_MU,BLIND_SIG)

It also reports the model-free inverse: the mean blind gain that would be needed
for phi_plant <= phi_base at each regime.

Usage:  python scripts/blind_gain_models.py [n_blocks] [n_seeds]
"""
import json, math, os, random, statistics, sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts.simulation.constants import (RANDOM_SEED, GAS_PHT_LARGE, MEV_MU,
                                          MEV_SIG, MEV_CAP, BLIND_MU, BLIND_SIG)
from scripts.simulation.environment import AMMPool, build_txpool
from scripts.blind_grid import (FIT_GRID, SUCCESS_GRID, PHI_BASE, load_regime,
                                mean_net, phi_plant)

CAL_FIT, CAL_SUCC = 0.10, 0.50          # the README's calibrated point


def draw(model):
    if model == "sandwich":
        return min(random.lognormvariate(MEV_MU, MEV_SIG), MEV_CAP)
    if model == "worse_of_two":
        return min(min(random.lognormvariate(MEV_MU, MEV_SIG), MEV_CAP),
                   min(random.lognormvariate(MEV_MU, MEV_SIG), MEV_CAP))
    if model == "blind_lognormal":
        return min(random.lognormvariate(BLIND_MU, BLIND_SIG), MEV_CAP)
    raise ValueError(model)


def record(n, seed, model):
    random.seed(seed); np.random.seed(seed)
    pool = AMMPool(1_000.0)
    has_dex = np.empty(n, bool); u1 = np.empty(n); u2 = np.empty(n); gain = np.empty(n)
    for i in range(n):
        txpool = build_txpool(random.randint(50, 200))
        has_dex[i] = any(t.is_dex for t in txpool)
        u1[i], u2[i] = random.random(), random.random()
        gain[i] = draw(model)
        pool.step()
    return has_dex, u1, u2, gain


def main():
    n_blocks = int(sys.argv[1]) if len(sys.argv) > 1 else 4000
    n_seeds  = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    models   = ["sandwich", "worse_of_two", "blind_lognormal"]
    out = {"n_blocks": n_blocks, "n_seeds": n_seeds, "results": {}}

    # realized mean of each payoff model
    print("payoff models (mean of 200k draws, ETH):")
    means = {}
    for m in models:
        random.seed(7)
        xs = [draw(m) for _ in range(200_000)]
        means[m] = statistics.mean(xs)
        print(f"  {m:16s} mean={means[m]:.5f}  median={statistics.median(xs):.6f}")

    for regime in ("cache2023", "real2026"):
        gas   = load_regime(regime, n_blocks)
        c_gas = gas * GAS_PHT_LARGE / 1e9
        med   = float(np.median(gas))
        print(f"\n=== {regime}: median base fee {med:.4f} gwei ===")
        print(f"{'model':16s} {'phi_plant @ calibrated':>24s} {'cells>phi_base':>16s}")
        reg = {}
        for m in models:
            runs = [record(n_blocks, RANDOM_SEED + 1000 * k, m) for k in range(n_seeds)]
            # calibrated cell
            vals = []
            for has_dex, u1, u2, gain in runs:
                hit = (u1 < CAL_FIT) & (u2 < CAL_SUCC)
                vals.append(phi_plant(has_dex, hit, gain, c_gas))
            fin = [v for v in vals if v is not None]
            cal = statistics.median(fin) if len(fin) == len(vals) else None
            # whole grid, one seed (cell count is stable across seeds)
            has_dex, u1, u2, gain = runs[0]
            over = 0
            for fit in FIT_GRID:
                for succ in SUCCESS_GRID:
                    v = phi_plant(has_dex, (u1 < fit) & (u2 < succ), gain, c_gas)
                    if v is None or v > PHI_BASE:
                        over += 1
            print(f"{m:16s} {('inf' if cal is None else f'{cal:.4f}'):>24s} "
                  f"{f'{over}/121':>16s}")
            reg[m] = {"phi_plant_calibrated": cal, "cells_over_phi_base": over,
                      "mean_gain_eth": means[m]}

        # model-free inverse: required mean blind gain for phi_plant <= phi_base
        # at the calibrated hit rate p = CAL_FIT * CAL_SUCC. Deterrence needs the
        # certain fee to cover the expected prize: phi * c_gas >= p * m.
        p = CAL_FIT * CAL_SUCC
        m_req = PHI_BASE * float(np.mean(c_gas)) / p
        print(f"  required mean blind gain for phi_plant <= {PHI_BASE} at p={p:.3f}: "
              f"{m_req:.6f} ETH  (${m_req*3000:,.2f} at ETH=$3,000)")
        reg["required_mean_gain_eth"] = m_req
        out["results"][regime] = reg

    json.dump(out, open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                     "..", "data", "blind_gain_models.json"), "w"), indent=1)
    print("\nwrote data/blind_gain_models.json")


if __name__ == "__main__":
    sys.exit(main())
