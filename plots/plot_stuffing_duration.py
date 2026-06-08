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
    # regime -> (label, colour, linestyle, marker).  The dynamic regime is
    # reported as the worst case over attacker strategies (pure or evading).
    "ethereum":    ("Ethereum",                  _DEEP[7], "-",  "o"),  # gray baseline
    "p2s_static":  ("P2S, flat $\\varphi$",       _DEEP[3], "--", "s"),  # red — the hole
    "p2s_dynamic": ("P2S, dynamic $\\varphi$",    _DEEP[2], "-",  "^"),  # green — the fix
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


def plot_mechanism_tradeoff(payload, out_path):
    """Two panels telling the reservation-fee design tradeoff at 1000 ETH:

    (a) Worst-case stuffing duration vs escalation slope.  Raising the
        utilization-gap slope plateaus *above* Ethereum (the evader retreats into
        the execution-fee regime, where the reservation slope is irrelevant);
        the occupancy-keyed fee, which cannot be evaded by executing, drops below
        Ethereum.

    (b) The price of that: the reservation fee a *benign* swapper pays over a
        sustained honest-congestion episode.  The gap fee never escalates (it
        keys on the unexecuted gap, which benign load does not produce); the
        occupancy fee, unable to tell benign congestion from a stuffer, taxes the
        honest user geometrically."""
    sns.set_theme(style="ticks")
    fig, (axL, axR) = plt.subplots(1, 2, figsize=(16, 6))

    # ── (a) tuning insensitivity ────────────────────────────────────────────
    ss = payload["slope_sweep"]
    slopes = np.array(ss["slopes"])
    axL.plot(slopes, ss["gap"], color=_DEEP[2], lw=2.6, marker="^", ms=7,
             label="P2S, gap-keyed $\\varphi$ (worst case)")
    axL.plot(slopes, ss["occupancy"], color=_DEEP[0], lw=2.6, marker="D", ms=7,
             label="P2S, occupancy-keyed $\\varphi$ (worst case)")
    axL.axhline(ss["ethereum"], color=_DEEP[7], lw=2.4, ls=":",
                label=f"Ethereum ({ss['ethereum']} blocks)")
    axL.set_xlabel("Reservation-fee slope $s$", fontsize=FS_LABEL, fontweight="bold")
    axL.set_ylabel("Worst-case blocks sustained", fontsize=FS_LABEL, fontweight="bold")
    axL.set_yscale("log")
    axL.tick_params(labelsize=FS_TICK)
    axL.legend(fontsize=FS_LEGEND - 1, loc="upper right", frameon=False)
    axL.grid(True, which="both", alpha=0.18, linestyle="--", color="gray")
    axL.set_axisbelow(True)
    axL.set_title(f"(a) Worst-case duration at "
                  f"{payload['tuning_ref_budget_eth']:.0f} ETH",
                  fontsize=FS_LEGEND + 2)

    # ── (b) benign congestion surcharge ──────────────────────────────────────
    bs = payload["benign_surcharge"]
    usd = 3000.0
    # Cap the panel at a realistic congestion horizon: a benign demand spike lasts
    # a handful of blocks before EIP-1559 self-corrects, so plotting the full
    # trajectory would reach economically meaningless values.
    horizon = min(21, len(bs["gap"]))
    x = np.arange(horizon)
    axR.plot(x, np.array(bs["gap"][:horizon]) * usd, color=_DEEP[2], lw=2.6,
             marker="^", ms=6, markevery=3, label="gap-keyed $\\varphi$")
    axR.plot(x, np.array(bs["occupancy"][:horizon]) * usd, color=_DEEP[0], lw=2.6,
             marker="D", ms=6, markevery=3, label="occupancy-keyed $\\varphi$")
    axR.set_xlabel("Block of sustained congestion", fontsize=FS_LABEL, fontweight="bold")
    axR.set_ylabel("Benign swap $F_{\\mathsf{res}}$ (USD)",
                   fontsize=FS_LABEL, fontweight="bold")
    axR.set_yscale("log")
    axR.tick_params(labelsize=FS_TICK)
    axR.legend(fontsize=FS_LEGEND, loc="upper left", frameon=False)
    axR.grid(True, which="both", alpha=0.18, linestyle="--", color="gray")
    axR.set_axisbelow(True)
    axR.set_title(f"(b) Honest-user cost ($g^{{\\mathsf{{limit}}}}$"
                  f"={bs['g_limit']//1000}k, ETH=\\${usd:.0f})",
                  fontsize=FS_LEGEND + 2)

    sns.despine(fig=fig)
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
    plot_mechanism_tradeoff(
        payload, os.path.join(FIGURES_DIR, "stuffing_mechanism_tradeoff.pdf"))


if __name__ == "__main__":
    main()
