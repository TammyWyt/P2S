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
    "ethereum":     ("Ethereum (execute)",                       _DEEP[7], "-",  "o"),  # gray baseline
    "p2s_static":   ("P2S, flat $\\varphi$ (no escalation)",      _DEEP[3], "--", "s"),  # red — the hole
    "p2s_dynamic":  ("P2S, dynamic $\\varphi$ (ours)",            _DEEP[2], "-",  "^"),  # green — the fix
    "p2s_adaptive": ("P2S, dynamic $\\varphi$ (best evasion)",    _DEEP[1], ":",  "D"),  # orange — the pincer
}
_ORDER = ["ethereum", "p2s_static", "p2s_dynamic", "p2s_adaptive"]


def plot_duration_by_budget(payload, out_path):
    sns.set_theme(style="ticks")
    fig, ax = plt.subplots(figsize=(10, 6))
    budgets = np.array(payload["budgets_eth"])
    blocks  = payload["blocks_sustained"]

    for regime in _ORDER:
        label, col, ls, mk = REGIME_STYLE[regime]
        ax.plot(budgets, np.array(blocks[regime]), label=label,
                color=col, lw=2.6, linestyle=ls, marker=mk, ms=6)

    # Log-log axes: the flat-phi regime is a straight unit-slope line (duration
    # linear in budget) while the two deterred regimes flatten out (duration
    # logarithmic in budget), so all three are legible on a single panel.
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("Attacker budget (ETH)", fontsize=FS_LABEL, fontweight="bold")
    ax.set_ylabel("Blocks sustained", fontsize=FS_LABEL, fontweight="bold")
    ax.tick_params(labelsize=FS_TICK)
    ax.legend(fontsize=FS_LEGEND, loc="upper left", frameon=False)
    ax.grid(True, which="both", alpha=0.18, linestyle="--", color="gray")
    ax.set_axisbelow(True)

    # Right-hand axis: blocks -> wall-clock hours at one slot per block.
    secax = ax.secondary_yaxis(
        "right",
        functions=(lambda b: b * SLOT_SECONDS / 3600.0,
                   lambda h: h * 3600.0 / SLOT_SECONDS),
    )
    secax.set_ylabel("Wall-clock (hours)", fontsize=FS_LABEL - 2, fontweight="bold")
    secax.tick_params(labelsize=FS_TICK - 2)

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
    ax.legend(fontsize=FS_LEGEND, loc="upper left", frameon=False)
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
