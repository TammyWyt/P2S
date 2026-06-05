#!/usr/bin/env python3
"""
Sustained block-stuffing (DDoS) figures for P2S.

Produces two plots from scripts.simulation.stuffing_duration:

  stuffing_duration_by_budget.pdf — attack duration (blocks / wall-clock) vs the
      attacker's budget, for Ethereum, P2S with a flat reservation fee, and P2S
      with the proposed occupancy-escalating reservation fee.  On log-log axes
      Ethereum and dynamic-phi are concave (duration ~ log budget) while the flat
      reservation fee is a straight unit-slope line (duration ~ linear in budget).

  stuffing_basefee_trajectory.pdf — the per-block ETH the attacker burns over a
      sustained attack: Ethereum's execution cost rises +12.5%/block, P2S's
      flat-fee reservation cost decays toward the floor (the attack gets cheaper),
      and the dynamic-phi reservation cost rises +12.5%/block, restoring the
      escalating deterrent.

All figures saved to figures/.
"""

import os
import sys

import matplotlib.pyplot as plt
import numpy as np
import seaborn as sns

# ── project path ──────────────────────────────────────────────────────────────
_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from scripts.simulation.stuffing_duration import run, SLOT_SECONDS

FIGURES_DIR = os.path.join(_REPO, "figures")

# Shared font sizes (match the other plot scripts)
FS_LABEL  = 24
FS_TICK   = 20
FS_LEGEND = 17

_DEEP = sns.color_palette("deep")
REGIME_STYLE = {
    # regime -> (label, colour, linestyle, marker)
    "ethereum":    ("Ethereum (execute)",        _DEEP[7], "-",  "o"),   # gray baseline
    "p2s_static":  ("P2S, flat $\\varphi$",       _DEEP[3], "--", "s"),   # red — the hole
    "p2s_dynamic": ("P2S, dynamic $\\varphi$",    _DEEP[2], "-",  "^"),   # green — the fix
}
_ORDER = ["ethereum", "p2s_static", "p2s_dynamic"]


def plot_duration_by_budget(payload, out_path):
    sns.set_theme(style="ticks")
    fig, ax = plt.subplots(figsize=(10, 6))
    budgets = np.array(payload["budgets_eth"])
    blocks  = payload["blocks_sustained"]

    for regime in _ORDER:
        label, col, ls, mk = REGIME_STYLE[regime]
        ax.plot(budgets, np.array(blocks[regime]), label=label,
                color=col, lw=2.6, linestyle=ls, marker=mk, ms=6)

    # Linear axes: the flat-phi regime is a literal straight line (duration linear
    # in budget); the two deterred regimes are ~3 orders of magnitude smaller and
    # collapse onto the axis, so a zoomed inset recovers their logarithmic shape.
    ax.set_xlim(left=0)
    ax.set_ylim(bottom=0)
    ax.set_xlabel("Attacker budget (ETH)", fontsize=FS_LABEL, fontweight="bold")
    ax.set_ylabel("Blocks sustained", fontsize=FS_LABEL, fontweight="bold")
    ax.tick_params(labelsize=FS_TICK)
    ax.legend(fontsize=FS_LEGEND, loc="lower right", frameon=False)
    ax.grid(True, alpha=0.18, linestyle="--", color="gray")
    ax.set_axisbelow(True)
    ax.yaxis.get_offset_text().set_fontsize(FS_TICK - 4)

    # Right-hand axis: blocks -> wall-clock hours at one slot per block.
    secax = ax.secondary_yaxis(
        "right",
        functions=(lambda b: b * SLOT_SECONDS / 3600.0,
                   lambda h: h * 3600.0 / SLOT_SECONDS),
    )
    secax.set_ylabel("Wall-clock (hours)", fontsize=FS_LABEL - 2, fontweight="bold")
    secax.tick_params(labelsize=FS_TICK - 2)

    # Inset: zoom to the two deterred regimes (Ethereum and dynamic-phi), whose
    # logarithmic-in-budget curvature is invisible on the main linear axes.
    axin = ax.inset_axes([0.30, 0.46, 0.46, 0.44])
    for regime in ("ethereum", "p2s_dynamic"):
        label, col, ls, mk = REGIME_STYLE[regime]
        axin.plot(budgets, np.array(blocks[regime]),
                  color=col, lw=2.2, linestyle=ls, marker=mk, ms=4)
    axin.set_xlim(left=0)
    axin.set_ylim(0, 55)
    axin.tick_params(labelsize=FS_TICK - 6)
    axin.grid(True, alpha=0.18, linestyle="--", color="gray")
    axin.set_axisbelow(True)
    axin.set_title("zoom: deterred regimes", fontsize=FS_LEGEND - 3)

    sns.despine(ax=ax, right=False)
    plt.tight_layout()
    plt.savefig(out_path, dpi=300, bbox_inches="tight")
    plt.close()
    print(f"Saved {out_path}")


def plot_basefee_trajectory(payload, out_path):
    sns.set_theme(style="ticks")
    fig, ax = plt.subplots(figsize=(10, 6))
    cost = payload["cost_trajectory_eth"]
    n    = len(next(iter(cost.values())))
    x    = np.arange(n)

    for regime in _ORDER:
        label, col, ls, mk = REGIME_STYLE[regime]
        ax.plot(x, np.array(cost[regime]), label=label,
                color=col, lw=2.6, linestyle=ls, marker=mk, ms=5, markevery=5)

    ax.set_yscale("log")
    ax.set_xlabel("Block of sustained attack", fontsize=FS_LABEL, fontweight="bold")
    ax.set_ylabel("Cost per block (ETH)", fontsize=FS_LABEL, fontweight="bold")
    ax.tick_params(labelsize=FS_TICK)
    ax.legend(fontsize=FS_LEGEND, loc="center left", frameon=False)
    ax.grid(True, alpha=0.18, linestyle="--", color="gray")
    ax.set_axisbelow(True)
    sns.despine(ax=ax)
    plt.tight_layout()
    plt.savefig(out_path, dpi=300, bbox_inches="tight")
    plt.close()
    print(f"Saved {out_path}")


def main():
    os.makedirs(FIGURES_DIR, exist_ok=True)
    print("Running sustained block-stuffing experiment …")
    payload = run()
    plot_duration_by_budget(
        payload, os.path.join(FIGURES_DIR, "stuffing_duration_by_budget.pdf"))
    plot_basefee_trajectory(
        payload, os.path.join(FIGURES_DIR, "stuffing_basefee_trajectory.pdf"))


if __name__ == "__main__":
    main()
