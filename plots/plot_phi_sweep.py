#!/usr/bin/env python3
"""
φ sweep figures for P2S.

Runs the agent-based sweep across PHI_SWEEP values and produces four plots:

  phi_activity.pdf    — attacker activity rate vs φ (line, per agent)
  phi_profit.pdf      — attacker mean net profit per block vs φ (line, per agent)
  phi_heatmap.pdf     — 2-D heatmap: base_gas_gwei (x) × φ (y) → total attacker profit
  phi_gas_params.pdf  — declared gas limit and effective maxFeePerGas vs φ

All figures saved to figures/.
"""

import os
import sys
import math
import random

import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import numpy as np
import seaborn as sns

# ── project path ──────────────────────────────────────────────────────────────
_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from scripts.simulation.sweep import run_sweep
from scripts.simulation.constants import (
    PHI_SWEEP, MEAN_GAS_GWEI, N_BLOCKS, RANDOM_SEED,
    GAS_PHT, GAS_PHT_LARGE, STUFF_GAS_DECLARED,
    WEI_PER_ETH, GWEI_PER_ETH,
)
from scripts.simulation.agents import (
    ALL_AGENTS, SandwichBot, FrontrunBot, BlindPlanterBot,
    BlockStufferBot, B2ProposerBot, CrossBlockArbBot,
)
from scripts.simulation.environment import AMMPool, build_txpool

FIGURES_DIR = os.path.join(_REPO, "figures")

# Shared font sizes (match across all plot scripts)
FS_LABEL  = 24
FS_TICK   = 20
FS_LEGEND = 18

# Only agents that can ever be active at some φ
_INFEASIBLE = {"SandwichBot", "FrontrunBot", "B2ProposerBot"}

# seaborn "deep" qualitative palette — consistent, colorblind-friendly
_DEEP = sns.color_palette("deep")
AGENT_COLORS = {
    "BlindPlanterBot":  _DEEP[0],   # steel blue
    "BlockStufferBot":  _DEEP[2],   # sage green
    "CrossBlockArbBot": _DEEP[4],   # lavender
}
AGENT_LABELS = {
    "BlindPlanterBot":  "Blind Planter",
    "BlockStufferBot":  "Block Stuffer",
    "CrossBlockArbBot": "Cross-Block Arb",
}


# ─────────────────────────────────────────────────────────────────────────────

def _run_sweep_cached():
    """Run phi sweep and return (phi_vals, activity, net)."""
    phi_vals = PHI_SWEEP
    print("Running φ sweep …")
    activity, net = run_sweep(phi_values=phi_vals, n_blocks=N_BLOCKS, gas_gwei=MEAN_GAS_GWEI)
    return phi_vals, activity, net


def _active_agents(activity):
    """Return agent names that are ever active (activity_rate > 0.01 at any φ)."""
    return [name for name, rates in activity.items()
            if name not in _INFEASIBLE and max(rates) > 0.01]


# ── Plot 1: Activity rate vs φ ────────────────────────────────────────────────

def plot_activity(phi_vals, activity, out_path):
    sns.set_theme(style="ticks")
    fig, ax = plt.subplots(figsize=(9, 5))
    agents = _active_agents(activity)
    for name in agents:
        ax.plot(phi_vals, activity[name],
                label=AGENT_LABELS.get(name, name),
                color=AGENT_COLORS.get(name, "#555"),
                lw=2.2, marker="o", ms=5)
    ax.set_xscale("log")
    ax.set_xlabel("φ (reservation fee multiplier)", fontsize=FS_LABEL, fontweight="bold")
    ax.set_ylabel("Activity rate", fontsize=FS_LABEL, fontweight="bold")
    ax.set_ylim(0, 1.05)
    ax.tick_params(labelsize=FS_TICK)
    ax.legend(fontsize=FS_LEGEND, loc="upper right")
    ax.grid(True, alpha=0.18, linestyle="--", color="gray")
    ax.set_axisbelow(True)
    sns.despine(ax=ax)
    plt.tight_layout()
    plt.savefig(out_path, dpi=300, bbox_inches="tight")
    plt.close()
    print(f"Saved {out_path}")


# ── Plot 2: Mean net profit vs φ ─────────────────────────────────────────────

def plot_profit(phi_vals, net, out_path):
    sns.set_theme(style="ticks")
    fig, ax = plt.subplots(figsize=(9, 5))
    agents = [name for name in net if name not in _INFEASIBLE]
    for name in agents:
        vals = net[name]
        ax.plot(phi_vals, vals,
                label=AGENT_LABELS.get(name, name),
                color=AGENT_COLORS.get(name, "#555"),
                lw=2.2, marker="o", ms=5)
    ax.axhline(0, color="gray", lw=1.0, ls="--", alpha=0.6)
    ax.set_xscale("log")
    ax.set_xlabel("φ (reservation fee multiplier)", fontsize=FS_LABEL, fontweight="bold")
    ax.set_ylabel("Mean net profit per block (ETH)", fontsize=FS_LABEL, fontweight="bold")
    ax.tick_params(labelsize=FS_TICK)
    ax.legend(fontsize=FS_LEGEND, loc="upper right")
    ax.grid(True, alpha=0.18, linestyle="--", color="gray")
    ax.set_axisbelow(True)
    sns.despine(ax=ax)
    plt.tight_layout()
    plt.savefig(out_path, dpi=300, bbox_inches="tight")
    plt.close()
    print(f"Saved {out_path}")


# ── Plot 3: 2D heatmap base_gas × φ → total attacker profit ──────────────────

def _sweep_2d(phi_vals, gas_vals, n_blocks=500):
    """Return 2-D array [len(gas_vals), len(phi_vals)] of total net profit."""
    from scripts.simulation.agents import ALL_AGENTS
    profit = np.zeros((len(gas_vals), len(phi_vals)))
    for gi, gp in enumerate(gas_vals):
        for pi, phi in enumerate(phi_vals):
            random.seed(RANDOM_SEED + gi * 10000 + pi * 1000)
            np.random.seed(RANDOM_SEED + gi * 10000 + pi * 1000)
            agents = [cls() for cls in ALL_AGENTS]
            pool   = AMMPool(1_000.0)
            for _ in range(n_blocks):
                txpool = build_txpool(random.randint(50, 200))
                for a in agents:
                    a.step(phi, pool, txpool, gp)
                pool.step()
            total_net = sum(
                a.mean_net for a in agents if a.name not in _INFEASIBLE
            )
            profit[gi, pi] = total_net
    return profit


def plot_heatmap(phi_vals, out_path):
    gas_vals = np.logspace(math.log10(0.01), math.log10(10.0), 12)
    print("Running 2-D heatmap sweep (this takes ~30 s) …")
    profit = _sweep_2d(phi_vals, gas_vals, n_blocks=500)

    sns.set_theme(style="ticks")
    fig, ax = plt.subplots(figsize=(10, 6))

    phi_labels = [f"{p:.3g}" for p in phi_vals]
    gas_labels = [f"{g:.3g}" for g in gas_vals]

    im = ax.imshow(profit, aspect="auto", origin="lower",
                   cmap=sns.color_palette("mako", as_cmap=True), interpolation="nearest")
    cbar = fig.colorbar(im, ax=ax)
    cbar.set_label("Total attacker net profit / block (ETH)", fontsize=FS_LEGEND)
    cbar.ax.tick_params(labelsize=FS_TICK - 2)

    ax.set_xticks(range(len(phi_vals)))
    ax.set_xticklabels(phi_labels, rotation=45, ha="right", fontsize=FS_TICK - 2)
    ax.set_yticks(range(len(gas_vals)))
    ax.set_yticklabels(gas_labels, fontsize=FS_TICK - 2)
    ax.set_xlabel("φ (reservation fee multiplier)", fontsize=FS_LABEL, fontweight="bold")
    ax.set_ylabel("Base gas price (gwei)", fontsize=FS_LABEL, fontweight="bold")
    plt.tight_layout()
    plt.savefig(out_path, dpi=300, bbox_inches="tight")
    plt.close()
    print(f"Saved {out_path}")


# ── Plot 4: Gas params (declared g_limit, maxFeePerGas) vs φ ─────────────────

def plot_gas_params(phi_vals, out_path):
    """
    Optimal declared gas limit and effective maxFeePerGas (≈ g_base × (1+φ)) vs φ.

    - BlockStufferBot declares STUFF_GAS_DECLARED until φ* ≈ 0.26.
    - BlindPlanterBot uses GAS_PHT_LARGE.
    - Effective maxFeePerGas = g_base × (1 + φ) in gwei.
    """
    from scripts.simulation.constants import STUFF_GAS_DECLARED, GAS_PHT_LARGE

    phi_arr  = np.array(phi_vals)
    g_base   = MEAN_GAS_GWEI   # post-Dencun Base L2

    # Declared g_limit per strategy (constant until deactivation)
    phi_stuffer_star = 0.26
    stuffer_limit = np.where(phi_arr <= phi_stuffer_star, STUFF_GAS_DECLARED, np.nan)
    planter_limit = np.where(phi_arr <= 1e6, GAS_PHT_LARGE, np.nan)   # always

    # Effective max fee per gas = base_fee × (1 + φ)
    eff_max_fee = g_base * (1.0 + phi_arr)

    sns.set_theme(style="ticks")
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(9, 8), sharex=True)

    # Top panel: declared gas limits — same colors as activity/profit plots
    ax1.plot(phi_arr, stuffer_limit, color=AGENT_COLORS["BlockStufferBot"], lw=2.2, marker="o", ms=4,
             label="Block Stuffer (declared g_limit)")
    ax1.plot(phi_arr, planter_limit, color=AGENT_COLORS["BlindPlanterBot"], lw=2.2, marker="s", ms=4,
             label="Blind Planter (declared g_limit)")
    ax1.set_xscale("log")
    ax1.set_ylabel("Declared gas limit (units)", fontsize=FS_LABEL, fontweight="bold")
    ax1.tick_params(labelsize=FS_TICK)
    ax1.legend(fontsize=FS_LEGEND)
    ax1.grid(True, alpha=0.18, linestyle="--", color="gray")
    ax1.set_axisbelow(True)
    ax1.yaxis.set_major_formatter(ticker.FuncFormatter(lambda x, _: f"{x/1e3:.0f}k"))
    sns.despine(ax=ax1)

    # Bottom panel: effective maxFeePerGas — use vlag warm tone to signal cost
    _vlag = sns.color_palette("vlag", n_colors=10)
    ax2.plot(phi_arr, eff_max_fee, color=_vlag[-2], lw=2.2, marker="o", ms=4,
             label="Effective maxFeePerGas = g_base × (1 + φ)")
    ax2.set_xscale("log")
    ax2.set_xlabel("φ (reservation fee multiplier)", fontsize=FS_LABEL, fontweight="bold")
    ax2.set_ylabel("maxFeePerGas (gwei)", fontsize=FS_LABEL, fontweight="bold")
    ax2.tick_params(labelsize=FS_TICK)
    ax2.legend(fontsize=FS_LEGEND)
    ax2.grid(True, alpha=0.18, linestyle="--", color="gray")
    ax2.set_axisbelow(True)
    sns.despine(ax=ax2)

    plt.tight_layout()
    plt.savefig(out_path, dpi=300, bbox_inches="tight")
    plt.close()
    print(f"Saved {out_path}")


# ─────────────────────────────────────────────────────────────────────────────

def main():
    os.makedirs(FIGURES_DIR, exist_ok=True)

    phi_vals, activity, net = _run_sweep_cached()

    plot_activity(phi_vals, activity,
                  os.path.join(FIGURES_DIR, "phi_activity.pdf"))
    plot_profit(phi_vals, net,
                os.path.join(FIGURES_DIR, "phi_profit.pdf"))
    plot_heatmap(phi_vals,
                 os.path.join(FIGURES_DIR, "phi_heatmap.pdf"))
    plot_gas_params(phi_vals,
                    os.path.join(FIGURES_DIR, "phi_gas_params.pdf"))


if __name__ == "__main__":
    main()
