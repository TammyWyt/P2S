#!/usr/bin/env python3
"""
Plot attack success rate, cost, and reward from simulation output.
Uses latest data/simulation_*.json. Saves to figures/.
"""

import glob
import json
import os
import sys

import matplotlib.pyplot as plt
import numpy as np
import seaborn as sns
from matplotlib.patches import Patch

DATA_DIR = "data"
FIGURES_DIR = "figures"

# Font sizes
FONTSIZE_YLABEL = 22
FONTSIZE_XTICK = 22
FONTSIZE_YTICK = 22
FONTSIZE_LEGEND = 22

VLAG_PALETTE = sns.color_palette("vlag", n_colors=10)
COLOR_ETH = VLAG_PALETTE[1]
COLOR_P2S = VLAG_PALETTE[-2]


def load_latest_simulation(data_dir: str):
    """Load the most recent simulation_*.json."""
    pattern = os.path.join(data_dir, "simulation_*.json")
    files = glob.glob(pattern)
    if not files:
        return None, None
    path = max(files, key=os.path.getmtime)
    with open(path, "r") as f:
        return json.load(f), path


def _collect_series(sim: dict):
    """Collect strategy names, success_rate, cost_eth (total and per-success), reward_eth."""
    names = []
    success_rates = []
    cost_total_eth = []
    cost_per_success_eth = []  # total_cost/successes; high when success rate is low
    reward_eth = []
    colors = []

    for name, s in sim.get("attack_strategies", {}).items():
        names.append(name.replace("_", " ").title())
        attempts = s.get("attempts") or 1
        successes = s.get("successes") or 0
        success_rates.append(100.0 * successes / attempts)
        cost_total_eth.append(s.get("total_cost_eth") or 0)
        # Effective cost per successful attack: high when success rate is low
        cps = s.get("cost_per_success_eth")
        if cps is not None:
            cost_per_success_eth.append(cps)
        else:
            cost_per_success_eth.append((s.get("total_cost_eth") or 0) / successes if successes else (s.get("total_cost_eth") or 0))
        reward_eth.append(s.get("total_gain_eth") or 0)
        colors.append(COLOR_ETH)

    for name, s in sim.get("attack_strategies_p2s", {}).items():
        names.append(name.replace("_", " ").replace("p2s", "").strip().title() or "Blind insert")
        attempts = s.get("attempts") or 1
        successes = s.get("successes") or 0
        success_rates.append(100.0 * successes / attempts)
        cost_total_eth.append(s.get("total_cost_eth") or 0)
        cps = s.get("cost_per_success_eth")
        if cps is not None:
            cost_per_success_eth.append(cps)
        else:
            cost_per_success_eth.append((s.get("total_cost_eth") or 0) / successes if successes else (s.get("total_cost_eth") or 0))
        reward_eth.append(s.get("total_gain_eth") or 0)
        colors.append(COLOR_P2S)

    return names, success_rates, cost_total_eth, cost_per_success_eth, reward_eth, colors


def plot_attack_success_cost_reward(sim_data: dict, figures_dir: str) -> None:
    """Save 3 separate plots: success rate (%), cost per success (ETH), reward (ETH)."""
    names, success_rates, cost_total_eth, cost_per_success_eth, reward_eth, colors = _collect_series(sim_data)
    if not names:
        print("No attack strategies in simulation data.", file=sys.stderr)
        return

    ymax = max(success_rates) * 1.15 if success_rates and max(success_rates) > 0 else 100
    sns.set_theme(style="ticks")

    # 1. Success rate (%)
    fig, ax = plt.subplots(figsize=(8, 5))
    x = np.arange(len(names))
    ax.bar(x, success_rates, color=colors, edgecolor="white", linewidth=1.2, width=0.72)
    ax.set_ylabel("Success rate (%)", fontsize=FONTSIZE_YLABEL, fontweight="bold")
    ax.set_xticks(x)
    ax.set_xticklabels(names, rotation=30, ha="right", fontsize=FONTSIZE_XTICK)
    ax.set_ylim(0, ymax)
    ax.tick_params(axis="y", labelsize=FONTSIZE_YTICK)
    legend_handles = [Patch(facecolor=COLOR_ETH, label="Ethereum"), Patch(facecolor=COLOR_P2S, label="P2S")]
    ax.legend(handles=legend_handles, fontsize=FONTSIZE_LEGEND, loc='upper right')
    sns.despine(ax=ax)
    plt.tight_layout()
    os.makedirs(figures_dir, exist_ok=True)
    plt.savefig(os.path.join(figures_dir, "attack_success_rate.pdf"), dpi=300, bbox_inches="tight")
    plt.show()
    plt.close()
    print(f"Saved {os.path.join(figures_dir, 'attack_success_rate.pdf')}")

    # 2. Cost per success (ETH)
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.bar(x, cost_per_success_eth, color=colors, edgecolor="white", linewidth=1.2, width=0.72)
    ax.set_ylabel("Cost per success (ETH)", fontsize=FONTSIZE_YLABEL, fontweight="bold")
    ax.set_xticks(x)
    ax.set_xticklabels(names, rotation=30, ha="right", fontsize=FONTSIZE_XTICK)
    ax.tick_params(axis="y", labelsize=FONTSIZE_YTICK)
    ax.legend(handles=legend_handles, fontsize=FONTSIZE_LEGEND, loc='upper right')
    sns.despine(ax=ax)
    plt.tight_layout()
    plt.savefig(os.path.join(figures_dir, "attack_cost_per_success.pdf"), dpi=300, bbox_inches="tight")
    plt.show()
    plt.close()
    print(f"Saved {os.path.join(figures_dir, 'attack_cost_per_success.pdf')}")

    # 3. Reward (ETH)
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.bar(x, reward_eth, color=colors, edgecolor="white", linewidth=1.2, width=0.72)
    ax.set_ylabel("Total reward (ETH)", fontsize=FONTSIZE_YLABEL, fontweight="bold")
    ax.set_xticks(x)
    ax.set_xticklabels(names, rotation=30, ha="right", fontsize=FONTSIZE_XTICK)
    ax.tick_params(axis="y", labelsize=FONTSIZE_YTICK)
    ax.legend(handles=legend_handles, fontsize=FONTSIZE_LEGEND, loc='upper right')
    sns.despine(ax=ax)
    plt.tight_layout()
    plt.savefig(os.path.join(figures_dir, "attack_reward.pdf"), dpi=300, bbox_inches="tight")
    plt.show()
    plt.close()
    print(f"Saved {os.path.join(figures_dir, 'attack_reward.pdf')}")


def main():
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    data_dir = os.path.join(repo_root, DATA_DIR)
    figures_dir = os.path.join(repo_root, FIGURES_DIR)

    sim_data, data_path = load_latest_simulation(data_dir)
    if not sim_data:
        print("No simulation_*.json found in data/. Run simulation first.", file=sys.stderr)
        sys.exit(1)
    print(f"Using {os.path.basename(data_path)}")

    plot_attack_success_cost_reward(sim_data, figures_dir)
    print("Done. Figures in", figures_dir)


if __name__ == "__main__":
    main()
