#!/usr/bin/env python3
"""
Figure 8: Agent-based φ sweep.

  (a) Agent activity rate vs φ — shows which attacks deactivate and when.
  (b) Analytical expected net profit vs φ — shows why deactivation happens.

Simulation logic lives in scripts/simulation/.
Run: python plots/plot_phi_agent_sweep.py
"""

import math
import os
import sys

import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import seaborn as sns

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, ".."))
sys.path.insert(0, _ROOT)

from scripts.simulation import run_sweep, gas_eth
from scripts.simulation.constants import (
    PHI_SWEEP, N_BLOCKS, MEAN_GAS_GWEI,
    E_MEV_GAIN, B2_MATCH_PROB, B2_N_PHTS, N_VALIDATORS, GAS_PHT,
    STUFF_E_BENEFIT, STUFF_N_PHTS, STUFF_GAS_DECLARED,
)

FIGURES_DIR = os.path.join(_ROOT, "figures")

VLAG   = sns.color_palette("vlag", n_colors=10)
COLORS = {
    "SandwichBot":      VLAG[0],
    "FrontrunBot":      VLAG[1],
    "BlindPlanterBot":  VLAG[-2],
    "BlockStufferBot":  "goldenrod",
    "B2ProposerBot":    VLAG[-3],
    "CrossBlockArbBot": "mediumpurple",
}
LINESTYLES = {
    "BlockStufferBot": "-.",
    "B2ProposerBot":   "-",
}


# ─────────────────────────────────────────────────────────────────────────────
# Analytical profit curves (Proposition 4 / §4.5)
# ─────────────────────────────────────────────────────────────────────────────

def _b2_analytic_ueth(phi: float, gp: float = MEAN_GAS_GWEI) -> float:
    """E[net per block] for B2ProposerBot (μETH). Zero for φ ≥ φ*."""
    exec_pht = gas_eth(gp, GAS_PHT)
    margin   = B2_MATCH_PROB * E_MEV_GAIN - exec_pht * (1.0 + phi)
    if margin <= 0:
        return 0.0
    return (1.0 / N_VALIDATORS) * B2_N_PHTS * margin * 1e6


def _stuffer_analytic_ueth(phi: float, gp: float = MEAN_GAS_GWEI) -> float:
    """E[net per block] for BlockStufferBot (μETH). Zero for φ ≥ φ*_stuffer."""
    exec_stuff = gas_eth(gp, STUFF_GAS_DECLARED)
    return max(STUFF_E_BENEFIT - STUFF_N_PHTS * phi * exec_stuff, 0.0) * 1e6


# ─────────────────────────────────────────────────────────────────────────────
# Plot
# ─────────────────────────────────────────────────────────────────────────────

def plot_sweep(phi_values, activity, net):
    sns.set_theme(style="ticks")
    fig, (ax_a, ax_b) = plt.subplots(1, 2, figsize=(13, 5))

    phi_star = 0.052

    # ── Panel (a): Activity rate ─────────────────────────────────────────────
    for name, ls in LINESTYLES.items():
        lw = 2.5 if name == "B2ProposerBot" else 2.0
        ax_a.plot(phi_values, activity[name],
                  color=COLORS[name], ls=ls, lw=lw,
                  marker="o" if name == "B2ProposerBot" else None,
                  markersize=5, label=name.replace("Bot", " Bot"),
                  zorder=4 if name == "B2ProposerBot" else 3)

    ax_a.plot([], [], color="steelblue", ls=(0, (3, 2)), lw=1.5,
              label="Sandwich / Frontrun / Blind /\nCrossBlock Bot  [info-blocked]")

    ax_a.axvline(phi_star, color="black", lw=1.2, ls="--", alpha=0.65, zorder=3)
    ax_a.text(phi_star + 0.006, 0.24,
              fr"$\varphi^*\!\approx\!{phi_star:.3f}$",
              fontsize=11, color="black", va="center")
    ax_a.axvline(0.10, color="dimgray", lw=1.0, ls=":", alpha=0.5, zorder=3)
    ax_a.text(0.102, 0.035, r"$\varphi=0.10$" + "\n(rec.)", fontsize=9, color="dimgray")

    ax_a.set_xlabel(r"Reservation-fee parameter $\varphi$", fontsize=13, fontweight="bold")
    ax_a.set_ylabel("Agent activity rate\n(fraction of blocks with E[net] > 0)",
                    fontsize=13, fontweight="bold")
    ax_a.set_xlim(0, max(phi_values))
    ax_a.set_ylim(-0.03, 1.08)
    ax_a.yaxis.set_major_formatter(mticker.PercentFormatter(xmax=1.0))
    ax_a.tick_params(labelsize=12)
    ax_a.legend(fontsize=9.5, loc="upper right", framealpha=0.92)
    ax_a.text(0.02, 0.97, "(a)", transform=ax_a.transAxes, fontsize=13, fontweight="bold", va="top")
    sns.despine(ax=ax_a)

    # ── Panel (b): Analytical profit curves ──────────────────────────────────
    phi_dense = np.linspace(0, 0.15, 400)

    ax_b.plot(phi_dense, [_b2_analytic_ueth(p) for p in phi_dense],
              color=COLORS["B2ProposerBot"], lw=2.5, ls="-",
              label="B2Proposer Bot  (analytical)", zorder=4)
    ax_b.plot(phi_dense, [_stuffer_analytic_ueth(p) for p in phi_dense],
              color=COLORS["BlockStufferBot"], lw=2.0, ls="-.",
              label="BlockStuffer Bot  (analytical)", zorder=3)

    ax_b.axhline(0, color="gray", lw=0.8, ls="--", alpha=0.6)
    ax_b.axvline(phi_star, color="black", lw=1.2, ls="--", alpha=0.65, zorder=3)
    ax_b.text(phi_star + 0.003, 20,
              fr"$\varphi^*\!\approx\!{phi_star:.3f}$", fontsize=10, color="black")
    ax_b.axvline(0.10, color="dimgray", lw=1.0, ls=":", alpha=0.5, zorder=3)
    ax_b.text(0.102, 20, r"$\varphi\!=\!0.10$" + "\n(rec.)", fontsize=9, color="dimgray")

    ax_b.set_xlabel(r"Reservation-fee parameter $\varphi$", fontsize=13, fontweight="bold")
    ax_b.set_ylabel(r"Expected net profit per block ($\mu$ETH)", fontsize=13, fontweight="bold")
    ax_b.set_xlim(0, 0.15)
    ax_b.set_ylim(bottom=-5)
    ax_b.tick_params(labelsize=12)
    ax_b.legend(fontsize=9.5, loc="upper right", framealpha=0.92)
    ax_b.text(0.02, 0.97, "(b)", transform=ax_b.transAxes, fontsize=13, fontweight="bold", va="top")
    sns.despine(ax=ax_b)

    plt.tight_layout()
    os.makedirs(FIGURES_DIR, exist_ok=True)
    out = os.path.join(FIGURES_DIR, "phi_agent_sweep.pdf")
    plt.savefig(out, dpi=300, bbox_inches="tight")
    plt.close()
    print(f"\nSaved {out}")


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    print("=" * 65)
    print("P2S Agent-Based phi Sweep")
    print(f"  {len(PHI_SWEEP)} phi values  x  {N_BLOCKS} blocks each")
    print("=" * 65)

    activity, net = run_sweep(PHI_SWEEP, N_BLOCKS, verbose=True)

    print(f"\n  {'Agent':<22}", end="")
    for phi in [0.00, 0.05, 0.10, 0.20]:
        if phi in PHI_SWEEP:
            print(f"  phi={phi:.2f}", end="")
    print()
    print("  " + "-" * 70)
    for name, vals in activity.items():
        print(f"  {name:<22}", end="")
        for phi in [0.00, 0.05, 0.10, 0.20]:
            if phi in PHI_SWEEP:
                print(f"  {vals[PHI_SWEEP.index(phi)]:>8.1%}", end="")
        print()

    print("\nGenerating figure...")
    plot_sweep(PHI_SWEEP, activity, net)
    print("Done.")


if __name__ == "__main__":
    main()
