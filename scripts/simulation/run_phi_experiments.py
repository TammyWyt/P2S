#!/usr/bin/env python3
"""
P2S φ Experiments
=================
Three experiments characterising the reservation-fee parameter φ:

  EXP-1  φ sweep          — activity rate and net profit across φ ∈ [0, 0.5]
  EXP-2  Gas sensitivity  — how φ* shifts as base-fee changes (30–200 gwei)
  EXP-3  Validator count  — how activity ceiling scales with N_validators

Results are printed and saved to data/phi_experiments.json.

Run from project root:
    python scripts/simulation/run_phi_experiments.py
"""

import json
import math
import os
import random
import sys

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
sys.path.insert(0, _ROOT)

from scripts.simulation.agents import (
    B2ProposerBot, BlockStufferBot, ALL_AGENTS,
)
from scripts.simulation.constants import (
    PHI_SWEEP, N_BLOCKS, MEAN_GAS_GWEI, RANDOM_SEED,
    GAS_PHT, B2_MATCH_PROB, E_MEV_GAIN, N_VALIDATORS,
    STUFF_N_PHTS, STUFF_GAS_DECLARED, STUFF_E_BENEFIT,
)
from scripts.simulation.environment import AMMPool, build_txpool, gas_eth
from scripts.simulation.sweep import run_sweep

DATA_DIR = os.path.join(_ROOT, "data")
OUTPUT  = os.path.join(DATA_DIR, "phi_experiments.json")

ACTIVITY_THRESH = 0.01   # below this → agent considered deactivated


# ─────────────────────────────────────────────────────────────────────────────
# Analytical helpers
# ─────────────────────────────────────────────────────────────────────────────

def phi_star_b2(gas_gwei: float = MEAN_GAS_GWEI) -> float:
    """Analytical B2ProposerBot breakeven: φ* = B2_MATCH_PROB·E[MEV]/exec_pht − 1."""
    exec_pht = gas_eth(gas_gwei, GAS_PHT)
    return B2_MATCH_PROB * E_MEV_GAIN / exec_pht - 1.0

def phi_star_stuffer(gas_gwei: float = MEAN_GAS_GWEI) -> float:
    """Analytical BlockStufferBot breakeven: φ*_s = STUFF_E_BENEFIT / (N·exec_stuff)."""
    exec_stuff = gas_eth(gas_gwei, STUFF_GAS_DECLARED)
    return STUFF_E_BENEFIT / (STUFF_N_PHTS * exec_stuff)


# ─────────────────────────────────────────────────────────────────────────────
# EXP-1: φ sweep
# ─────────────────────────────────────────────────────────────────────────────

def exp1_phi_sweep(n_blocks: int = N_BLOCKS) -> dict:
    """Run the full PHI_SWEEP and collect per-agent activity + net profit."""
    print(f"\n{'='*65}")
    print(f"EXP-1  φ sweep  ({len(PHI_SWEEP)} values × {n_blocks} blocks each)")
    print(f"{'='*65}")

    activity, net = run_sweep(PHI_SWEEP, n_blocks, gas_gwei=MEAN_GAS_GWEI, verbose=True)

    # Pretty table
    cols = [0.00, 0.05, 0.10, 0.20, 0.50]
    idxs = {phi: i for i, phi in enumerate(PHI_SWEEP) if phi in cols}
    print(f"\n  {'Agent':<22}", end="")
    for phi in cols:
        if phi in idxs:
            print(f"  φ={phi:.2f}", end="")
    print()
    print("  " + "─" * 65)
    for name, vals in activity.items():
        print(f"  {name:<22}", end="")
        for phi in cols:
            if phi in idxs:
                print(f"  {vals[idxs[phi]]:>6.1%}", end="")
        print()

    # Empirical φ* — first φ where activity drops below threshold
    empirical_phi_star: dict[str, float | None] = {}
    for name, vals in activity.items():
        dropped = [PHI_SWEEP[i] for i, v in enumerate(vals) if v < ACTIVITY_THRESH]
        empirical_phi_star[name] = dropped[0] if dropped else None

    print(f"\n  Empirical φ* (activity < {ACTIVITY_THRESH:.0%}):")
    print(f"  {'Agent':<22}  {'Empirical':>12}  {'Analytical':>12}")
    print("  " + "─" * 50)
    analytical = {
        "B2ProposerBot":    phi_star_b2(),
        "BlockStufferBot":  phi_star_stuffer(),
    }
    for name in [a.__name__ for a in ALL_AGENTS]:
        emp = empirical_phi_star.get(name)
        ana = analytical.get(name, float("nan"))
        emp_s = f"{emp:.3f}" if emp is not None else "never"
        ana_s = f"{ana:.5f}" if not math.isnan(ana) else "n/a"
        print(f"  {name:<22}  {emp_s:>12}  {ana_s:>12}")

    return {
        "phi_values": PHI_SWEEP,
        "activity":   {k: [round(v, 6) for v in vs] for k, vs in activity.items()},
        "net_eth":    {k: [round(v, 9) for v in vs] for k, vs in net.items()},
        "empirical_phi_star": empirical_phi_star,
        "analytical_phi_star": {k: round(v, 6) for k, v in analytical.items()},
        "n_blocks": n_blocks,
        "gas_gwei": MEAN_GAS_GWEI,
    }


# ─────────────────────────────────────────────────────────────────────────────
# EXP-2: Gas price sensitivity
# ─────────────────────────────────────────────────────────────────────────────

GAS_PRICES_GWEI = [0.005, 0.010, 0.020, 0.074, 0.200, 0.500, 1.000]  # Base L2 range (gwei)

def exp2_gas_sensitivity(n_blocks: int = 1_000) -> dict:
    """
    For each base-fee level, find empirical and analytical φ* for B2ProposerBot.
    Uses a fine-grained φ grid around the expected breakeven.
    """
    print(f"\n{'='*65}")
    print(f"EXP-2  Gas-price sensitivity  ({len(GAS_PRICES_GWEI)} gas levels × {n_blocks} blocks each)")
    print(f"{'='*65}")

    results_emp  = []
    results_anal = []

    for gp in GAS_PRICES_GWEI:
        # build a fine grid around the analytical breakeven
        phi_a = phi_star_b2(gp)
        fine  = sorted(set(
            [round(x, 4) for x in np.linspace(max(0, phi_a - 0.05), phi_a + 0.10, 30)]
            + [0.0, 0.005]
        ))
        activity, _ = run_sweep(fine, n_blocks, gas_gwei=gp, verbose=False)
        b2_vals = activity["B2ProposerBot"]
        dropped = [fine[i] for i, v in enumerate(b2_vals) if v < ACTIVITY_THRESH]
        emp = dropped[0] if dropped else None
        results_emp.append(emp)
        results_anal.append(phi_a)
        emp_s = f"{emp:.4f}" if emp is not None else "never"
        print(f"  gp={gp:>7.3f} gwei  φ*_anal={phi_a:.4f}  φ*_emp={emp_s}")

    return {
        "gas_prices_gwei": GAS_PRICES_GWEI,
        "phi_star_analytical": [round(v, 6) for v in results_anal],
        "phi_star_empirical":  [
            round(v, 6) if v is not None else None for v in results_emp
        ],
        "n_blocks": n_blocks,
    }


# ─────────────────────────────────────────────────────────────────────────────
# EXP-3: Validator count effect on activity ceiling
# ─────────────────────────────────────────────────────────────────────────────

N_VALIDATORS_RANGE = [1, 2, 5, 10, 20, 50, 100]
_PHI_BELOW_STAR    = 0.02    # φ well below φ* — agent should be active whenever proposer

def exp3_validator_count(n_blocks: int = 5_000) -> dict:
    """
    Show B2ProposerBot activity ceiling = 1/N_validators at φ < φ*.
    Patches N_VALIDATORS in the agents module per iteration.
    """
    import scripts.simulation.agents as _agents_mod
    import scripts.simulation.constants as _const_mod

    print(f"\n{'='*65}")
    print(f"EXP-3  N_validators effect  ({len(N_VALIDATORS_RANGE)} values × {n_blocks} blocks)")
    print(f"       fixed φ = {_PHI_BELOW_STAR}  (below φ*)")
    print(f"{'='*65}")

    rates_empirical   = []
    rates_theoretical = []

    for nv in N_VALIDATORS_RANGE:
        # Monkey-patch N_VALIDATORS so B2ProposerBot.step() uses it
        _agents_mod.N_VALIDATORS = nv
        _const_mod.N_VALIDATORS  = nv

        random.seed(RANDOM_SEED)
        np.random.seed(RANDOM_SEED)

        agent = B2ProposerBot()
        pool  = AMMPool(1_000.0)
        for i in range(n_blocks):
            txpool = build_txpool(random.randint(50, 200))
            agent.step(_PHI_BELOW_STAR, pool, txpool, MEAN_GAS_GWEI)
            pool.step()

        emp  = agent.activity_rate
        theo = 1.0 / nv
        rates_empirical.append(round(emp, 6))
        rates_theoretical.append(round(theo, 6))
        print(f"  N_validators={nv:>4d}  theoretical={theo:.4f}  empirical={emp:.4f}"
              f"  error={abs(emp-theo):.4f}")

    # Restore original
    _agents_mod.N_VALIDATORS = N_VALIDATORS
    _const_mod.N_VALIDATORS  = N_VALIDATORS

    return {
        "n_validators":       N_VALIDATORS_RANGE,
        "activity_theoretical": rates_theoretical,
        "activity_empirical":   rates_empirical,
        "phi_fixed": _PHI_BELOW_STAR,
        "n_blocks":  n_blocks,
    }


# ─────────────────────────────────────────────────────────────────────────────
# EXP-5: High-resolution profit sweep (200k blocks per φ)
# ─────────────────────────────────────────────────────────────────────────────

PHI_PROFIT = list(np.geomspace(0.01, 1200, 16))    # log-spaced around new φ*_b2 ≈ 831


def exp5_profit_sweep(n_blocks: int = 200_000) -> dict:
    """
    Mean net profit and SE for B2ProposerBot across the active φ range.
    Uses 200k blocks per φ so the signal (~0.00045 ETH) clears the noise (SE ~0.00014).
    Per-block profits reconstructed from agent._costs / _gains lists.
    """
    print(f"\n{'='*65}")
    print(f"EXP-5  Profit sweep  ({len(PHI_PROFIT)} φ values × {n_blocks:,} blocks each)")
    print(f"{'='*65}")

    means, ses = [], []

    for phi_idx, phi in enumerate(PHI_PROFIT):
        random.seed(RANDOM_SEED + phi_idx * 19)
        np.random.seed(RANDOM_SEED + phi_idx * 19)

        agent = B2ProposerBot()
        pool  = AMMPool(1_000.0)
        for _ in range(n_blocks):
            txpool = build_txpool(random.randint(50, 200))
            agent.step(phi, pool, txpool, MEAN_GAS_GWEI)
            pool.step()

        # Per-block net: (gain-cost) for active blocks, 0 for inactive
        active_nets = [g - c for g, c in zip(agent._gains, agent._costs)]
        per_block   = np.array(active_nets + [0.0] * (agent._total - agent._active))
        mean_v = float(np.mean(per_block))
        se_v   = float(np.std(per_block, ddof=1) / np.sqrt(agent._total))
        means.append(round(mean_v, 9))
        ses.append(round(se_v, 9))
        print(f"  phi={phi:.4f}  mean={mean_v:.6f} ETH  se={se_v:.6f} ETH")

    return {
        "phi_values":  PHI_PROFIT,
        "mean_net":    means,
        "se_net":      ses,
        "n_blocks":    n_blocks,
        "gas_gwei":    MEAN_GAS_GWEI,
    }


# ─────────────────────────────────────────────────────────────────────────────
# EXP-6: Monte Carlo profit sweep (K independent short runs per φ)
# ─────────────────────────────────────────────────────────────────────────────

PHI_ACTIVE = list(np.geomspace(0.01, 1200, 14))    # log-spaced around new φ*_b2 ≈ 831


def exp6_profit_mc(K: int = 1_000, n_blocks: int = 500) -> dict:
    """
    K independent runs of n_blocks blocks per φ value.
    Each run gets its own seed → empirical distribution of mean_net.
    CI is taken from the 2.5th–97.5th percentiles across K runs, so it
    is valid for the fat-tailed lognormal MEV distribution without any
    normality assumption.
    """
    print(f"\n{'='*65}")
    print(f"EXP-6  Monte Carlo profit  "
          f"(K={K} × {n_blocks} blocks × {len(PHI_ACTIVE)} φ values)")
    print(f"{'='*65}")

    all_means: dict[str, list[float]] = {}

    for phi_idx, phi in enumerate(PHI_ACTIVE):
        run_means = []
        for k in range(K):
            seed = RANDOM_SEED + phi_idx * 10_007 + k
            random.seed(seed)
            np.random.seed(seed)

            agent = B2ProposerBot()
            pool  = AMMPool(1_000.0)
            for _ in range(n_blocks):
                txpool = build_txpool(random.randint(50, 200))
                agent.step(phi, pool, txpool, MEAN_GAS_GWEI)
                pool.step()

            active_nets = [g - c for g, c in zip(agent._gains, agent._costs)]
            per_block   = np.array(active_nets + [0.0] * (agent._total - agent._active))
            run_means.append(float(np.mean(per_block)))

        arr = np.array(run_means)
        mu  = float(np.mean(arr))
        lo  = float(np.percentile(arr, 2.5))
        hi  = float(np.percentile(arr, 97.5))
        all_means[str(phi)] = [round(v, 9) for v in run_means]
        print(f"  phi={phi:.4f}  mean={mu:.6f}  95%CI=[{lo:.6f}, {hi:.6f}] ETH")

    return {
        "phi_values":   PHI_ACTIVE,
        "run_means":    all_means,   # K means per φ for full empirical distribution
        "K":            K,
        "n_blocks":     n_blocks,
        "gas_gwei":     MEAN_GAS_GWEI,
    }


# ─────────────────────────────────────────────────────────────────────────────
# EXP-4: B2ProposerBot activity rate vs φ at multiple gas-price levels
# ─────────────────────────────────────────────────────────────────────────────

GAS_PRICES_SWEEP = [0.005, 0.020, MEAN_GAS_GWEI, 0.200]       # Base L2 range (gwei)
PHI_FINE = list(np.geomspace(0.01, 15_000, 30))               # log-spaced; covers all φ* values


def exp4_gas_activity(n_blocks: int = 2_000) -> dict:
    """
    B2ProposerBot activity rate across φ at four base-fee levels.
    Activity rate is a Bernoulli estimate — reliable at n_blocks=2000.
    """
    print(f"\n{'='*65}")
    print(f"EXP-4  Gas × φ activity  "
          f"({len(GAS_PRICES_SWEEP)} gas levels × {len(PHI_FINE)} φ values × {n_blocks} blocks)")
    print(f"{'='*65}")

    b2_activity: dict[str, list[float]] = {}
    for gp in GAS_PRICES_SWEEP:
        activity, _ = run_sweep(PHI_FINE, n_blocks, gas_gwei=gp, verbose=False)
        b2_activity[str(gp)] = [round(v, 6) for v in activity["B2ProposerBot"]]
        phi_star_emp = next(
            (PHI_FINE[i] for i, v in enumerate(activity["B2ProposerBot"])
             if v < ACTIVITY_THRESH),
            None,
        )
        emp_s = f"{phi_star_emp:.4f}" if phi_star_emp is not None else "never"
        print(f"  gp={gp:>7.3f} gwei  φ*_emp={emp_s}")

    return {
        "gas_prices_gwei": GAS_PRICES_SWEEP,
        "phi_values":      PHI_FINE,
        "b2_activity":     b2_activity,
        "n_blocks":        n_blocks,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    random.seed(RANDOM_SEED)
    np.random.seed(RANDOM_SEED)

    print("P2S φ Experiments")
    print(f"  Analytical φ* (B2Proposer)   = {phi_star_b2():.3f}")
    print(f"  Analytical φ* (BlockStuffer) = {phi_star_stuffer():.4f}")

    results = {}
    results["exp1_phi_sweep"]       = exp1_phi_sweep()
    results["exp2_gas_sensitivity"] = exp2_gas_sensitivity()
    results["exp3_validator_count"] = exp3_validator_count()
    results["exp4_gas_activity"]    = exp4_gas_activity()
    results["exp5_profit_sweep"]    = exp5_profit_sweep()
    results["exp6_profit_mc"]       = exp6_profit_mc()

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(OUTPUT, "w") as fh:
        json.dump(results, fh, indent=2)
    print(f"\nResults saved → {OUTPUT}")


if __name__ == "__main__":
    main()
