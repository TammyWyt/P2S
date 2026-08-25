#!/usr/bin/env python3
"""
End-to-end pipeline: simulate → write data files → regenerate all figures.

Usage:
    python scripts/run_all.py            # 1000-block run (default)
    python scripts/run_all.py 500        # shorter run for quick testing

Steps:
    1. Run P2S vs Ethereum PoS block simulation (simulator.py)
       → writes data/block_ledger_1000.json
       → writes data/mev_comparison.json
    2. Run φ sweep with confidence intervals (plot_phi_sweep.py)
       → writes figures/phi_activity.pdf, phi_profit.pdf,
                  phi_heatmap.pdf, phi_stuffer_net.pdf
    3. Run welfare comparison plot (plot_welfare.py)
       → writes figures/welfare_cdf.pdf
    4. Run MEV comparison plot (plot_mev_comparison.py)
       → writes figures/mev_totals_by_type.pdf, cumulative_mev.pdf,
                  cost_gain_comparison.pdf
    5. Run network latency plots (plot_latency.py)
    6. Run sustained block-stuffing / DDoS plots (plot_stuffing_duration.py)
       → writes figures/stuffing_duration_by_budget.pdf,
                  stuffing_basefee_trajectory.pdf
"""

import os
import sys

# Ensure repo root is on the path regardless of where this script is called from
_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

os.chdir(_REPO)


def step(label: str):
    print(f"\n{'='*70}")
    print(f"  {label}")
    print(f"{'='*70}")


# ── Step 1: Simulation ────────────────────────────────────────────────────────

step("Step 1/4 — Running block simulation")

num_blocks = 1000
if len(sys.argv) > 1:
    try:
        num_blocks = int(sys.argv[1])
    except ValueError:
        print(f"Warning: could not parse '{sys.argv[1]}' as int; using {num_blocks}")

from scripts.simulation.simulator import P2SSimulator

sim = P2SSimulator()
sim.run_simulation(num_blocks)
sim.save_results()
sim.save_ledger_json("data/block_ledger_1000.json")
sim.save_mev_comparison_json("data/mev_comparison.json")

print("Step 1 done.")

# ── Step 2: φ sweep ───────────────────────────────────────────────────────────
# Disabled: plots/plot_phi_sweep.py does not exist, so this step raised
# ModuleNotFoundError and aborted the run.  No figure in the write-up comes from
# the φ sweep; the sweep driver itself still lives in scripts/simulation/sweep.py
# and can be called directly.  Restore this step if that plot script is written.
#
# step("Step 2/4 — Running φ sweep (3 reps × 21 φ values × 3000 blocks each)")
#
# import plots.plot_phi_sweep as phi_sweep
#
# phi_sweep.main()
# print("Step 2 done.")

# ── Step 3: Welfare CDF ───────────────────────────────────────────────────────

step("Step 3/4 — Generating welfare comparison plot")

import plots.plot_welfare as welfare

welfare.main()
print("Step 3 done.")

# ── Step 4: MEV comparison ────────────────────────────────────────────────────

step("Step 4/4 — Generating MEV comparison plots")

import plots.plot_mev_comparison as mev_cmp

mev_cmp.main()
print("Step 4 done.")

# ── Step 5: Latency analysis ──────────────────────────────────────────────────

step("Step 5/6 — Generating network latency figures")

import plots.plot_latency as latency

latency.main()
print("Step 5 done.")

# ── Step 6: Sustained block-stuffing (DDoS) ──────────────────────────────────

step("Step 6/6 — Generating sustained block-stuffing figures")

import plots.plot_stuffing_duration as stuffing

stuffing.main()
print("Step 6 done.")

# ── Summary ───────────────────────────────────────────────────────────────────

step("All steps complete")
print(f"Figures written to: {os.path.join(_REPO, 'figures/')}")
print(f"Data files written to: {os.path.join(_REPO, 'data/')}")
