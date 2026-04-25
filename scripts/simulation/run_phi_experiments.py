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

GAS_PRICES_GWEI = [20.0, 30.0, 58.577, 80.0, 100.0, 150.0, 200.0]

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
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    print("P2S φ Experiments")
    print(f"  Analytical φ* (B2Proposer)   = {phi_star_b2():.5f}")
    print(f"  Analytical φ* (BlockStuffer) = {phi_star_stuffer():.6f}")

    results = {}
    results["exp1_phi_sweep"]       = exp1_phi_sweep()
    results["exp2_gas_sensitivity"] = exp2_gas_sensitivity()
    results["exp3_validator_count"] = exp3_validator_count()

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(OUTPUT, "w") as fh:
        json.dump(results, fh, indent=2)
    print(f"\nResults saved → {OUTPUT}")


if __name__ == "__main__":
    main()
