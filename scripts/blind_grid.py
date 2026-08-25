#!/usr/bin/env python3
"""Blind-planting deterrence grid: BLIND_FIT x BLIND_SUCCESS, 11 x 11.

README.md claims the residual uncertainty in BLIND_FIT and BLIND_SUCCESS (both
tagged "not directly observable from public data") is bounded by an 11 x 11 grid
sweep. No such sweep existed. This is it.

For each grid cell we report

    phi_plant = the smallest reservation fraction at which the blind planter's
                realized mean net profit per block is <= 0,

found by bisection on realized simulation output. The planter is forced to plant
every block, so what is measured is the profitability of the attack itself
(eq. eu-plant), not the bot's own rationality gate.

Method. Per block we record the state BlindPlanterBot.act() consumes: whether the
txpool holds a DEX target, the two uniform gate draws, the realized blind-payoff
draw (AMMPool.blind_profit: the worse of two MEV draws), and the block's base fee. Cells then differ only in the gate
threshold, so one recorded run serves the whole grid and phi enters as pure
arithmetic. That arithmetic is asserted equal to the real act() at import time
(see _selftest), so the fast path is a re-evaluation of the shipped agent, not a
re-implementation of it. The gain is drawn every block rather than only on a hit;
the draws are independent by construction, and holding them fixed across cells is
the same common-random-numbers device sweep.py already uses across phi.

Two base-fee regimes, both real mainnet data, both evaluated on base fee alone
(F_res is defined on the base fee):

    cache2023 -- data/ethereum_blocks_cache.json, heights 18,748,996-18,750,000,
                 the window the paper calibrates on (median 45.0 gwei, pre-Dencun)
    real2026  -- data/basefee_windows.json, 12 x 1024-block windows sampled over
                 the past year (median 0.12 gwei)

Usage:  python scripts/blind_grid.py [n_blocks] [n_seeds]
"""
import json, os, random, statistics, sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts.simulation import agents as agents_mod
from scripts.simulation.agents import BlindPlanterBot, _sample_mev_gain
from scripts.simulation.environment import AMMPool, build_txpool, gas_eth
from scripts.simulation.constants import RANDOM_SEED, GAS_PHT_LARGE

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "data")
PHI_BASE = 0.20            # the paper's deployed baseline

FIT_GRID     = [round(0.05 * i, 3) for i in range(11)]   # 0.00 .. 0.50
SUCCESS_GRID = [round(0.10 * i, 3) for i in range(11)]   # 0.00 .. 1.00


def _net_block(phi, has_dex, hit, gain, gp):
    """Exact restatement of BlindPlanterBot.act()'s (cost, gain) arithmetic."""
    f_res     = gas_eth(gp, GAS_PHT_LARGE) * phi
    exec_cost = gas_eth(gp, GAS_PHT_LARGE)
    if not has_dex or not hit or gain <= exec_cost:
        return -f_res
    return gain - max(f_res, exec_cost)


def _selftest(n=400):
    """Assert _net_block reproduces the shipped agent's act() exactly."""
    bot = BlindPlanterBot()
    for case_fit, case_succ, hit in ((1.0, 1.0, True), (0.0, 0.0, False)):
        agents_mod.BLIND_FIT, agents_mod.BLIND_SUCCESS = case_fit, case_succ
        for k in range(n):
            gp  = 0.05 + (k % 97) * 0.7
            phi = [0.0, 0.05, 0.2, 1.0, 7.5][k % 5]
            random.seed(10_000 + k)
            pool, txpool = AMMPool(1_000.0), build_txpool(random.randint(50, 200))
            cost, gain = bot.act(phi, pool, txpool, gp)
            real = gain - cost
            # replay the same stream: two gate draws, then the gain draw
            random.seed(10_000 + k)
            pool2, txpool2 = AMMPool(1_000.0), build_txpool(random.randint(50, 200))
            has_dex = any(t.is_dex for t in txpool2)
            random.random(); random.random()
            g = min(_sample_mev_gain(), _sample_mev_gain()) if (has_dex and hit) else 0.0
            fast = _net_block(phi, has_dex, hit, g, gp)
            assert abs(real - fast) < 1e-15, (case_fit, k, phi, real, fast)
    print(f"selftest OK: _net_block matches BlindPlanterBot.act() on {2*n} cases")


def load_regime(name, n):
    """Per-block base fees in gwei, cycled to length n. No 1-gwei flooring: that
    floor in load_gas_prices is an artifact of the 2023 cache and would erase the
    very regime this script measures."""
    if name == "cache2023":
        cache = json.load(open(os.path.join(DATA, "ethereum_blocks_cache.json")))
        bf = []
        for b in cache.values():
            if not isinstance(b, dict) or "base_fee" not in b:
                continue
            v = float(b["base_fee"])
            bf.append(v / 1e9 if v > 1e9 else v)
        bf = [x for x in bf if x > 0]
    else:
        w = json.load(open(os.path.join(DATA, "basefee_windows.json")))
        bf = [x for win in w["windows"] for x in win["base_fees_gwei"]]
    return np.array([bf[i % len(bf)] for i in range(n)])


def record(gas_prices, seed):
    """One pass of the real environment: per-block (has_dex, u1, u2, gain)."""
    n = len(gas_prices)
    random.seed(seed); np.random.seed(seed)
    pool = AMMPool(1_000.0)
    has_dex = np.empty(n, bool); u1 = np.empty(n); u2 = np.empty(n); gain = np.empty(n)
    for i in range(n):
        txpool = build_txpool(random.randint(50, 200))
        has_dex[i] = any(t.is_dex for t in txpool)
        u1[i], u2[i] = random.random(), random.random()
        gain[i] = min(_sample_mev_gain(), _sample_mev_gain())
        pool.step()
    return has_dex, u1, u2, gain


def mean_net(phi, has_dex, hit, gain, c_gas):
    """Vectorized mean net per block. c_gas = execution gas cost per plant (ETH)."""
    f_res = c_gas * phi
    win   = has_dex & hit & (gain > c_gas)
    return float(np.where(win, gain - np.maximum(f_res, c_gas), -f_res).mean())


def phi_plant(has_dex, hit, gain, c_gas, hi=500.0):
    """Smallest phi with mean net <= 0. 0.0 if execution gas alone deters it;
    None if the attack survives phi = hi."""
    if mean_net(0.0, has_dex, hit, gain, c_gas) <= 0:
        return 0.0
    if mean_net(hi, has_dex, hit, gain, c_gas) > 0:
        return None
    lo = 0.0
    while hi - lo > 1e-5:
        mid = (lo + hi) / 2
        if mean_net(mid, has_dex, hit, gain, c_gas) > 0:
            lo = mid
        else:
            hi = mid
    return hi


def main():
    n_blocks = int(sys.argv[1]) if len(sys.argv) > 1 else 4000
    n_seeds  = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    _selftest()
    results = {}

    for regime in ("cache2023", "real2026"):
        gas   = load_regime(regime, n_blocks)
        c_gas = gas * GAS_PHT_LARGE / 1e9          # ETH per plant, per block
        med   = float(np.median(gas))
        print(f"\n=== {regime}: median base fee {med:.4f} gwei | "
              f"{n_blocks} blocks x {n_seeds} seeds | plant = {GAS_PHT_LARGE:,} gas ===")
        runs = [record(gas, RANDOM_SEED + 1000 * k) for k in range(n_seeds)]

        print("phi_plant, median over seeds.  '.' = deterred by execution gas alone at phi=0")
        print("fit\\succ" + "".join(f"{s:>9.1f}" for s in SUCCESS_GRID))
        grid = {}
        for fit in FIT_GRID:
            row = []
            for succ in SUCCESS_GRID:
                vals = []
                for has_dex, u1, u2, gain in runs:
                    hit = (u1 < fit) & (u2 < succ)
                    vals.append(phi_plant(has_dex, hit, gain, c_gas))
                fin = [v for v in vals if v is not None]
                v = statistics.median(fin) if len(fin) == len(vals) else None
                grid[f"{fit},{succ}"] = v
                row.append(v)
            cells = "".join("      inf" if v is None else
                            ("        ." if v == 0 else f"{v:>9.3f}") for v in row)
            print(f"{fit:>7.2f} {cells}")

        over = sum(1 for v in grid.values() if v is None or v > PHI_BASE)
        nz   = [v for v in grid.values() if v not in (None, 0.0)]
        cal  = grid.get("0.1,0.5")
        print(f"  cells with phi_plant > phi_base={PHI_BASE}: {over}/{len(grid)}")
        if nz:
            print(f"  non-trivial cells: min={min(nz):.3f} median={statistics.median(nz):.3f} "
                  f"max={max(nz):.3f}")
        print(f"  calibrated cell (BLIND_FIT=0.10, BLIND_SUCCESS=0.50): phi_plant="
              f"{'inf' if cal is None else f'{cal:.4f}'}")
        results[regime] = {"median_base_fee_gwei": med, "cells_over_phi_base": over,
                           "calibrated_phi_plant": cal, "grid": grid}

    out = os.path.join(DATA, "blind_grid.json")
    json.dump({"n_blocks": n_blocks, "n_seeds": n_seeds, "phi_base": PHI_BASE,
               "gas_units_per_plant": GAS_PHT_LARGE, "fit_grid": FIT_GRID,
               "success_grid": SUCCESS_GRID, "results": results}, open(out, "w"), indent=1)
    print("\nwrote", os.path.normpath(out))


if __name__ == "__main__":
    sys.exit(main())
