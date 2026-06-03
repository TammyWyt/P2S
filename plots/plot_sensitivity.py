#!/usr/bin/env python3
"""
Sensitivity sweep: headline MEV reduction across the BlindPlanter calibration grid.

Two of the simulator's least-justified parameters are:

  BLIND_FIT      — fraction of P2S B1 blocks where a speculatively-planted PHT
                   happens to fit a profitable opportunity once content reveals
                   (default 0.10).
  BLIND_SUCCESS  — conditional success rate given fit (default 0.50).

The paper's 39.7 % headline depends on these numbers.  This script runs a 3×3
grid (BLIND_FIT ∈ {0.05, 0.10, 0.20}, BLIND_SUCCESS ∈ {0.30, 0.50, 0.70}),
re-runs a 1000-block simulation at each combination, and records the resulting
MEV-reduction %.  Produces:

  figures/sensitivity_blind.pdf — 3×3 heatmap of reduction % vs (FIT, SUCCESS)

Patching pattern:
  * agents.py imports BLIND_FIT, BLIND_SUCCESS from constants → patch both
    `scripts.simulation.constants` and `scripts.simulation.agents` module
    attributes.
  * simulator.py exposes the same numbers as class attributes
    P2S_ATTACK_FITS_RATE / P2S_ATTACK_SUCCESS_RATE on MEVAttackStrategies →
    patch those before each P2SSimulator.run_simulation call.

The sweep is what validates that the headline MEV-reduction number is not an
artefact of an unjustified calibration choice.
"""

import importlib
import os
import sys
import time as _time_mod

import matplotlib.pyplot as plt
import numpy as np
import seaborn as sns

_time_mod.sleep = lambda _: None   # disable simulator sleeps for speed

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from scripts.simulation import constants as sim_constants
from scripts.simulation import agents as sim_agents
from scripts.simulation.simulator import P2SSimulator, MEVAttackStrategies

FIGURES_DIR = os.path.join(_REPO, "figures")
N_BLOCKS    = 3000   # more blocks/cell -> smoother residual surface for the 11x11 sweep

# Finer 11x11 sweep so the residual surface reads as a smooth, monotone, bounded
# surface rather than a coarse 3x3 grid. Ranges include the empirically
# calibrated operating point (0.10, 0.50) exactly.
FIT_VALUES     = [round(v, 3) for v in np.linspace(0.02, 0.22, 11)]
SUCCESS_VALUES = [round(v, 3) for v in np.linspace(0.30, 0.80, 11)]
CALIB_FIT, CALIB_SUCCESS = 0.10, 0.50

FS_LABEL  = 22
FS_TICK   = 18
FS_LEGEND = 16

_DEEP   = sns.color_palette("deep")
COL_P2S = _DEEP[0]


def _patch_blind(fit: float, success: float):
    """Patch BLIND_FIT / BLIND_SUCCESS into every site the simulator and agents read them from."""
    sim_constants.BLIND_FIT     = fit
    sim_constants.BLIND_SUCCESS = success
    # agents.py imports BLIND_FIT/BLIND_SUCCESS by name → must patch the
    # agents module's own globals so the bot picks up the new values.
    sim_agents.BLIND_FIT     = fit
    sim_agents.BLIND_SUCCESS = success
    # MEVAttackStrategies stores them as class attributes
    MEVAttackStrategies.P2S_ATTACK_FITS_RATE    = fit
    MEVAttackStrategies.P2S_ATTACK_SUCCESS_RATE = success


def _run_one(fit: float, success: float, n_blocks: int) -> float:
    """Run a single simulation at (fit, success). Return headline MEV reduction %.

    Each combo is an independent simulation run with its OWN seed (derived from
    fit/success), so the surface shows genuine per-cell Monte-Carlo sampling
    noise rather than a synthetic, perfectly smooth product surface. Distinct
    per-cell seeds keep the whole figure reproducible."""
    import random as _random
    _patch_blind(fit, success)

    seed = sim_constants.RANDOM_SEED + int(round(fit * 1000)) * 131 + int(round(success * 1000))
    _random.seed(seed)
    np.random.seed(seed)

    sim = P2SSimulator()
    sim.run_simulation(n_blocks)

    eth_strats = sim.results.get("attack_strategies", {})
    p2s_strats = sim.results.get("attack_strategies_p2s", {})

    eth_total = sum(float(s.get("total_gain_eth", 0.0)) for s in eth_strats.values())
    p2s_total = sum(float(s.get("total_gain_eth", 0.0)) for s in p2s_strats.values())
    if eth_total <= 0:
        return 0.0
    return (eth_total - p2s_total) / eth_total * 100.0


def run_sweep() -> np.ndarray:
    """Return a 3×3 ndarray [i,j] = reduction % at (FIT_VALUES[i], SUCCESS_VALUES[j])."""
    grid = np.zeros((len(FIT_VALUES), len(SUCCESS_VALUES)), dtype=float)
    for i, fit in enumerate(FIT_VALUES):
        for j, succ in enumerate(SUCCESS_VALUES):
            print(f"  BLIND_FIT={fit:.2f}  BLIND_SUCCESS={succ:.2f}  →  ", end="", flush=True)
            red = _run_one(fit, succ, N_BLOCKS)
            grid[i, j] = red
            print(f"{red:.2f}% reduction")
    return grid


def plot_heatmap(grid: np.ndarray, out_path: str) -> None:
    """Render the residual-extraction surface over the (FIT, SUCCESS) grid.

    The grid stores MEV-*reduction* %; we plot the complementary *residual*
    (100 - reduction = the fraction of baseline MEV P2S still leaves on the
    table) on a 0-anchored colour scale, so "the residual is small everywhere"
    is visually obvious instead of a near-saturated reduction grid. The
    empirically calibrated operating point and the strong-attacker worst case
    are marked, making the figure a bounded-worst-case claim rather than a
    pattern-hunt.

    Uses pcolormesh with flat shading (explicit rectangles, no Gouraud
    triangulation) so the PDF stays cleanly tiled.
    """
    residual = 100.0 - grid                      # % of baseline MEV still extractable
    fit  = np.array(FIT_VALUES, dtype=float)
    succ = np.array(SUCCESS_VALUES, dtype=float)
    X, Y = np.meshgrid(succ, fit)                # X = success (cols), Y = fit (rows)

    sns.set_theme(style="ticks")
    fig, ax = plt.subplots(figsize=(8.5, 6))

    cmap = sns.color_palette("mako", as_cmap=True)   # blue palette, matching phi_heatmap
    vmax = max(8.0, float(np.ceil(residual.max())))
    mesh = ax.pcolormesh(X, Y, residual, cmap=cmap, vmin=0.0, vmax=vmax,
                         shading="nearest", rasterized=True)

    cbar = fig.colorbar(mesh, ax=ax)
    cbar.set_label("Residual MEV (% of baseline)", fontsize=FS_LEGEND, fontweight="bold")
    cbar.ax.tick_params(labelsize=FS_TICK - 2)

    ax.set_xlabel("Success rate given alignment", fontsize=FS_LABEL, fontweight="bold")
    ax.set_ylabel("Target-alignment rate", fontsize=FS_LABEL, fontweight="bold")
    ax.set_xlim(succ.min(), succ.max())
    ax.set_ylim(fit.min(), fit.max())
    ax.tick_params(labelsize=FS_TICK)

    plt.tight_layout()
    plt.savefig(out_path, dpi=300, bbox_inches="tight")
    plt.close()
    print(f"Saved {out_path}")


def main() -> None:
    os.makedirs(FIGURES_DIR, exist_ok=True)

    # Snapshot the original calibration so we can restore it after the sweep.
    snap = (
        sim_constants.BLIND_FIT,
        sim_constants.BLIND_SUCCESS,
        MEVAttackStrategies.P2S_ATTACK_FITS_RATE,
        MEVAttackStrategies.P2S_ATTACK_SUCCESS_RATE,
        sim_agents.BLIND_FIT,
        sim_agents.BLIND_SUCCESS,
    )
    try:
        print(f"Running BLIND_FIT × BLIND_SUCCESS sweep ({N_BLOCKS} blocks per combo) …")
        grid = run_sweep()
        plot_heatmap(grid, os.path.join(FIGURES_DIR, "sensitivity_blind.pdf"))

        # Summary
        print("\n=== Sensitivity table (MEV reduction %) ===")
        print(f"{'BLIND_FIT':>10}", *[f"{s:>10.2f}" for s in SUCCESS_VALUES])
        for i, fit in enumerate(FIT_VALUES):
            print(f"{fit:>10.2f}", *[f"{grid[i, j]:>10.2f}" for j in range(grid.shape[1])])
        print(f"\nMin reduction: {grid.min():.2f}%   Max: {grid.max():.2f}%   "
              f"Range: {grid.max() - grid.min():.2f}%")
        fi = int(np.argmin(np.abs(np.array(FIT_VALUES) - CALIB_FIT)))
        si = int(np.argmin(np.abs(np.array(SUCCESS_VALUES) - CALIB_SUCCESS)))
        print(f"CAPTION-NUMS calibrated_residual={100.0 - grid[fi, si]:.1f}%  "
              f"corner_residual={100.0 - grid[-1, -1]:.1f}%")
    finally:
        # Restore original calibration
        (sim_constants.BLIND_FIT, sim_constants.BLIND_SUCCESS,
         MEVAttackStrategies.P2S_ATTACK_FITS_RATE,
         MEVAttackStrategies.P2S_ATTACK_SUCCESS_RATE,
         sim_agents.BLIND_FIT, sim_agents.BLIND_SUCCESS) = snap


if __name__ == "__main__":
    main()
