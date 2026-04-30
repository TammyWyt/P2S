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
    """Run phi sweep and return (phi_vals, activity, net)."""
    phi_vals = PHI_SWEEP
    print("Running φ sweep …")
    activity, net = run_sweep(phi_values=phi_vals, n_blocks=N_BLOCKS)
    return phi_vals, activity, net


def _active_agents(activity):
    """Return agent names that are ever active (activity_rate > 0.01 at any φ)."""
    return [name for name, rates in activity.items()
            if name not in _INFEASIBLE and max(rates) > 0.01]


# ── Plot 1: Activity rate vs φ ────────────────────────────────────────────────

def plot_activity(phi_vals, activity, out_path):
    sns.set_theme(style="ticks")
    fig, ax = plt.subplots(figsize=(9, 5))
    # Show all non-infeasible agents so the reader sees which are deterred by φ
    # vs which are already unprofitable from information hiding alone.
    agents = [n for n in activity if n not in _INFEASIBLE]
    linestyles = {
        "BlockStufferBot":  "-",
        "BlindPlanterBot":  "--",
        "CrossBlockArbBot": ":",
    }
    for name in agents:
        ax.plot(phi_vals, activity[name],
                label=AGENT_LABELS.get(name, name),
                color=AGENT_COLORS.get(name, "#555"),
                lw=2.2, marker="o", ms=5,
                linestyle=linestyles.get(name, "-"))
    ax.set_xscale("log")
    ax.set_xlabel("φ (reservation fee multiplier)", fontsize=FS_LABEL, fontweight="bold")
    ax.set_ylabel("Activity rate", fontsize=FS_LABEL, fontweight="bold")
    ax.set_ylim(-0.05, 1.1)
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
    BlockStuffer economics: how the attack earns and why φ deters it.

    The attacker submits STUFF_N_PHTS PHTs each declaring STUFF_GAS_DECLARED
    gas units to monopolise B1 block capacity.  At B1 they pay:
        F_res = N_phts × φ × g_declared × effective_gas_price   (burned, non-refundable)
    The monopoly gain STUFF_E_BENEFIT is constant (independent of φ).
    The attack is profitable only while F_res < STUFF_E_BENEFIT, i.e. φ < φ*.

    Top panel  — absolute ETH: F_res cost at p10/median/p90 gas price vs constant gain
    Bottom panel — net profit (gain − F_res) showing the sign change at φ*
    """
    phi_arr = np.array(phi_vals)

    # Historical gas price percentiles from block cache
    hist = sorted(load_gas_prices(1005))
    n    = len(hist)
    gp_levels = [
        (hist[n // 10],    "p10 base fee",    0.40),
        (hist[n // 2],     "median base fee", 0.75),
        (hist[9 * n // 10], "p90 base fee",   1.00),
    ]

    col   = AGENT_COLORS["BlockStufferBot"]
    UETH  = 1e6   # display in µETH for readability

    sns.set_theme(style="ticks")
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(9, 8), sharex=True)

    # ── Panel 1: cost vs gain (µETH) ──────────────────────────────────────────
    benefit_ueth = STUFF_E_BENEFIT * UETH
    ax1.axhline(benefit_ueth, color="black", lw=1.8, ls="--",
                label=f"Monopoly gain  = {benefit_ueth:.0f} µETH  (constant, independent of φ)")

    for gp, label, alpha in gp_levels:
        fres = np.array([STUFF_N_PHTS * phi * gas_eth(gp, STUFF_GAS_DECLARED) * UETH
                         for phi in phi_arr])
        phi_star = STUFF_E_BENEFIT / (STUFF_N_PHTS * gas_eth(gp, STUFF_GAS_DECLARED))
        ax1.plot(phi_arr, fres, color=col, alpha=alpha, lw=2.2, marker="o", ms=4,
                 label=f"F_res at {label} ({gp:.1f} gwei)  [φ* ≈ {phi_star:.2g}]")

    ax1.set_xscale("log")
    ax1.set_ylim(0, benefit_ueth * 3.2)   # clip at ~3× gain so crossover is centre-frame
    ax1.set_ylabel("ETH per block (µETH)", fontsize=FS_LABEL, fontweight="bold")
    ax1.tick_params(labelsize=FS_TICK)
    ax1.legend(fontsize=FS_LEGEND - 3, loc="upper left")
    ax1.grid(True, alpha=0.18, linestyle="--", color="gray")
    ax1.set_axisbelow(True)
    sns.despine(ax=ax1)

    # ── Panel 2: net profit = gain − F_res (µETH) ─────────────────────────────
    ax2.axhline(0, color="gray", lw=1.2, ls="--", alpha=0.7)
    for gp, label, alpha in gp_levels:
        net = np.array([(STUFF_E_BENEFIT - STUFF_N_PHTS * phi * gas_eth(gp, STUFF_GAS_DECLARED)) * UETH
                        for phi in phi_arr])
        ax2.plot(phi_arr, net, color=col, alpha=alpha, lw=2.2, marker="o", ms=4,
                 label=f"{label} ({gp:.1f} gwei)")

    # Shade profit region for median
    gp_med = hist[n // 2]
    net_med = np.array([(STUFF_E_BENEFIT - STUFF_N_PHTS * phi * gas_eth(gp_med, STUFF_GAS_DECLARED)) * UETH
                        for phi in phi_arr])
    ax2.fill_between(phi_arr, net_med, 0,
                     where=(net_med > 0), alpha=0.12, color=col, label="_nolegend_")

    ax2.set_xscale("log")
    ax2.set_ylim(-benefit_ueth * 1.5, benefit_ueth * 1.2)  # keep transition in view
    ax2.set_xlabel("φ (reservation fee multiplier)", fontsize=FS_LABEL, fontweight="bold")
    ax2.set_ylabel("Net profit (µETH/block)", fontsize=FS_LABEL, fontweight="bold")
    ax2.tick_params(labelsize=FS_TICK)
    ax2.legend(fontsize=FS_LEGEND - 3, loc="upper right")
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
