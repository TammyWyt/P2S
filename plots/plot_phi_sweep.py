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
    PHI_SWEEP, PRIORITY_FEE_GWEI, N_BLOCKS, RANDOM_SEED,
    GAS_PHT_LARGE, STUFF_GAS_DECLARED, STUFF_N_PHTS, STUFF_E_BENEFIT,
    WEI_PER_ETH, GWEI_PER_ETH,
)
from scripts.simulation.environment import load_gas_prices, gas_eth
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
    "CrossBlockArbBot": "Arbitrage",
}


# ─────────────────────────────────────────────────────────────────────────────

def _run_sweep_cached():
    """Run phi sweep and return (phi_vals, activity, net, activity_se, net_se)."""
    phi_vals = PHI_SWEEP
    print("Running φ sweep …")
    activity, net, activity_se, net_se = run_sweep(phi_values=phi_vals, n_blocks=N_BLOCKS)
    return phi_vals, activity, net, activity_se, net_se


def _active_agents(activity):
    """Return agent names that are ever active (activity_rate > 0.01 at any φ)."""
    return [name for name, rates in activity.items()
            if name not in _INFEASIBLE and max(rates) > 0.01]


# ── Plot 1: Activity rate vs φ ────────────────────────────────────────────────

def plot_activity(phi_vals, activity, out_path, activity_se=None):
    sns.set_theme(style="ticks")
    fig, ax = plt.subplots(figsize=(10, 5))
    agents = [n for n in activity if n not in _INFEASIBLE]
    linestyles = {
        "BlockStufferBot":  "-",
        "BlindPlanterBot":  "--",
        "CrossBlockArbBot": ":",
    }
    phi_arr = np.array(phi_vals)
    for name in agents:
        vals = np.array(activity[name])
        col  = AGENT_COLORS.get(name, "#555")
        ax.plot(phi_arr, vals,
                label=AGENT_LABELS.get(name, name),
                color=col, lw=2.2, marker="o", ms=5,
                linestyle=linestyles.get(name, "-"))
        if activity_se and name in activity_se:
            se = np.array(activity_se[name])
            ax.fill_between(phi_arr, np.maximum(0, vals - se), np.minimum(1, vals + se),
                            alpha=0.15, color=col)
    ax.set_xscale("symlog", linthresh=1e-4)
    ax.set_xlim(left=0)
    ax.set_xlabel("Reservation fee ratio φ", fontsize=FS_LABEL, fontweight="bold")
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

def plot_profit(phi_vals, net, out_path, net_se=None):
    sns.set_theme(style="ticks")
    fig, ax = plt.subplots(figsize=(10, 5))
    agents = [name for name in net if name not in _INFEASIBLE]
    phi_arr = np.array(phi_vals)
    for name in agents:
        vals = np.array(net[name])
        col  = AGENT_COLORS.get(name, "#555")
        ax.plot(phi_arr, vals,
                label=AGENT_LABELS.get(name, name),
                color=col, lw=2.2, marker="o", ms=5)
        if net_se and name in net_se:
            se = np.array(net_se[name])
            ax.fill_between(phi_arr, np.maximum(0, vals - se), vals + se,
                            alpha=0.15, color=col)
    ax.set_xscale("symlog", linthresh=1e-4)
    ax.set_xlim(left=0)
    ax.set_ylim(bottom=0)
    ax.set_xlabel("Reservation fee ratio φ", fontsize=FS_LABEL, fontweight="bold")
    ax.set_ylabel("Net profit / block (ETH)", fontsize=FS_LABEL, fontweight="bold")
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
    gas_vals = np.logspace(math.log10(10.0), math.log10(80.0), 12)  # realistic mainnet range
    print("Running 2-D heatmap sweep (this takes ~30 s) …")
    profit = _sweep_2d(phi_vals, gas_vals, n_blocks=500)

    # Trim to last phi column where any gas price still has non-zero profit
    last_active = max(
        (pi for pi in range(len(phi_vals)) if profit[:, pi].sum() > 0),
        default=0,
    )
    phi_vals  = phi_vals[:last_active + 1]
    profit    = profit[:, :last_active + 1]

    sns.set_theme(style="ticks")
    fig, ax = plt.subplots(figsize=(9, 5))

    phi_labels = [f"{p:.2g}" for p in phi_vals]
    gas_labels = [f"{g:.3g}" for g in gas_vals]

    im = ax.imshow(profit, aspect="auto", origin="lower",
                   cmap=sns.color_palette("mako", as_cmap=True), interpolation="nearest")
    cbar = fig.colorbar(im, ax=ax)
    cbar.set_label("Net profit / block (ETH)", fontsize=FS_LEGEND)
    cbar.ax.tick_params(labelsize=FS_TICK - 2)

    ax.set_xticks(range(len(phi_vals)))
    ax.set_xticklabels(phi_labels, rotation=45, ha="right", fontsize=FS_TICK - 2)
    ax.set_yticks(range(len(gas_vals)))
    ax.set_yticklabels(gas_labels, fontsize=FS_TICK - 2)
    ax.set_xlabel("Reservation fee ratio φ", fontsize=FS_LABEL, fontweight="bold")
    ax.set_ylabel("Base gas price (gwei)", fontsize=FS_LABEL, fontweight="bold")
    plt.tight_layout()
    plt.savefig(out_path, dpi=300, bbox_inches="tight")
    plt.close()
    print(f"Saved {out_path}")


# ── Plot 4: Gas params (declared g_limit, maxFeePerGas) vs φ ─────────────────

def _gas_params_data(phi_vals):
    """Shared data prep for the two BlockStuffer economics plots."""
    hist = sorted(load_gas_prices(1005))
    n    = len(hist)
    gp_levels = [
        (hist[n // 10],     "low gas",    0.40),
        (hist[n // 2],      "median gas", 0.75),
        (hist[9 * n // 10], "high gas",   1.00),
    ]
    return np.array(phi_vals), hist, n, gp_levels


def plot_stuffer_net(phi_vals, out_path):
    """
    Rational net profit (ETH/block) vs φ.

    Clipped at 0: a rational agent exits when e_net ≤ 0 and earns nothing,
    not negative profit.  The drop to zero marks φ* (deterrence threshold).
    At φ = 0 (no reservation fee) the attacker keeps the full monopoly gain.
    """
    phi_arr, hist, n, gp_levels = _gas_params_data(phi_vals)
    col     = _DEEP[0]
    benefit = STUFF_E_BENEFIT

    sns.set_theme(style="ticks")
    fig, ax = plt.subplots(figsize=(9, 5))

    for gp, label, alpha in gp_levels:
        net = np.maximum(0.0, np.array(
            [STUFF_E_BENEFIT - STUFF_N_PHTS * phi * gas_eth(gp, STUFF_GAS_DECLARED)
             for phi in phi_arr]))
        ax.plot(phi_arr, net, color=col, alpha=alpha, lw=2.2, marker="o", ms=4,
                label=f"{label} ({gp:.1f} gwei)")

    ax.set_xscale("symlog", linthresh=1e-4)
    ax.set_xlim(left=0)
    ax.set_ylim(0, benefit * 1.18)
    ax.set_xlabel("Reservation fee ratio φ", fontsize=FS_LABEL, fontweight="bold")
    ax.set_ylabel("Net profit (ETH/block)", fontsize=FS_LABEL, fontweight="bold")
    ax.tick_params(labelsize=FS_TICK)
    ax.legend(fontsize=FS_LEGEND - 3, loc="upper right")
    ax.grid(True, alpha=0.18, linestyle="--", color="gray")
    ax.set_axisbelow(True)
    sns.despine(ax=ax)
    plt.tight_layout()
    plt.savefig(out_path, dpi=300, bbox_inches="tight")
    plt.close()
    print(f"Saved {out_path}")


# ── Combined: net profit vs φ, colour = bot, shade = gas price ───────────────

def plot_profit_by_gas(phi_vals, out_path, n_blocks=N_BLOCKS):
    """One plot subsuming the per-bot profit curve and the per-gas stuffer curve:
    net profit/block vs φ, where COLOUR encodes the bot and SHADE (alpha) encodes
    the gas-price level (low/median/high). Each active bot gets three lines."""
    from matplotlib.lines import Line2D

    phi_arr, hist, n, gp_levels = _gas_params_data(phi_vals)
    phi_a = np.array(phi_vals, dtype=float)

    sns.set_theme(style="ticks")
    fig, ax = plt.subplots(figsize=(11, 6))

    # Only BlockStuffer has a non-zero residual surface; BlindPlanter and
    # Arbitrage earn zero at every gas level and are omitted.
    active = set()
    for gp, _label, alpha in gp_levels:
        _, net, _, _ = run_sweep(phi_values=list(phi_vals), n_blocks=n_blocks,
                                 gas_gwei=gp, verbose=False)
        for name in net:
            if name in _INFEASIBLE:
                continue
            vals = np.array(net[name], dtype=float)
            if np.nanmax(np.abs(vals)) < 1e-9:
                continue
            active.add(name)
            col = AGENT_COLORS.get(name, "#555")
            ax.plot(phi_a, vals, color=col, alpha=alpha, lw=2.4, marker="o", ms=4)

    ax.set_xscale("symlog", linthresh=1e-4)
    ax.set_xlim(left=0)
    ax.set_ylim(bottom=0)
    ax.set_xlabel("Reservation fee ratio φ", fontsize=FS_LABEL, fontweight="bold")
    ax.set_ylabel("Net profit / block (ETH)", fontsize=FS_LABEL, fontweight="bold")
    ax.tick_params(labelsize=FS_TICK)
    ax.grid(True, alpha=0.18, linestyle="--", color="gray")
    ax.set_axisbelow(True)

    # Single legend: shade → gas price (only BlockStuffer is plotted; stated in
    # the caption rather than a one-entry bot legend).
    stuffer_col = AGENT_COLORS["BlockStufferBot"]
    gas_handles = [Line2D([0], [0], color=stuffer_col, lw=3.2, alpha=a,
                          label=f"{lab} ({gp:.0f} gwei)")
                   for gp, lab, a in gp_levels]
    ax.legend(handles=gas_handles, loc="upper right", fontsize=FS_LEGEND - 2)

    sns.despine(ax=ax)
    plt.tight_layout()
    plt.savefig(out_path, dpi=300, bbox_inches="tight")
    plt.close()
    print(f"Saved {out_path}")


# ─────────────────────────────────────────────────────────────────────────────

def main():
    os.makedirs(FIGURES_DIR, exist_ok=True)

    phi_vals, activity, net, activity_se, net_se = _run_sweep_cached()

    plot_activity(phi_vals, activity,
                  os.path.join(FIGURES_DIR, "phi_activity.pdf"),
                  activity_se=activity_se)
    plot_profit(phi_vals, net,
                os.path.join(FIGURES_DIR, "phi_profit.pdf"),
                net_se=net_se)
    plot_heatmap(phi_vals,
                 os.path.join(FIGURES_DIR, "phi_heatmap.pdf"))
    plot_stuffer_net(phi_vals,
                     os.path.join(FIGURES_DIR, "phi_stuffer_net.pdf"))


if __name__ == "__main__":
    main()
