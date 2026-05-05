#!/usr/bin/env python3
"""
MEV comparison plots (Ethereum vs P2S).
Uses a single cached comparison dataset in data/ — no testnet rerun required.
"""

import glob
import json
import os
import sys

import matplotlib.pyplot as plt
import numpy as np
import seaborn as sns

DATA_DIR = "data"
FIGURES_DIR = "figures"

# Shared font sizes (match across all plot scripts)
FS_LABEL  = 24
FS_TICK   = 20
FS_LEGEND = 18

# vlag: index -2 = warm red (Ethereum, more MEV); index 1 = cool blue (P2S, less MEV)
_VLAG     = sns.color_palette("vlag", n_colors=10)
COLOR_ETH = _VLAG[-2]   # warm red  — Ethereum PoS
COLOR_P2S = _VLAG[1]    # cool blue — P2S

# Default paths: use one comparison file (generated once from inspect + compare)
def _find_latest(path_pattern: str):
    files = glob.glob(path_pattern)
    if not files:
        return None
    return max(files, key=os.path.getmtime)


def load_comparison(data_dir: str = DATA_DIR):
    """Load MEV comparison JSON from data/. Prefers mev_comparison.json, else latest mev_comparison_*.json."""
    canonical = os.path.join(data_dir, "mev_comparison.json")
    if os.path.isfile(canonical):
        with open(canonical, "r") as f:
            return json.load(f)
    path = _find_latest(os.path.join(data_dir, "mev_comparison_*.json"))
    if path:
        with open(path, "r") as f:
            return json.load(f)
    return None


def plot_mev_totals(comparison_data: dict, out_path: str) -> None:
    """Bar chart: Total MEV by type (Eth vs P2S)."""
    mev_by_type = comparison_data.get("mev_by_type", {})
    if not mev_by_type:
        return

    sns.set_theme(style="ticks")
    types = []
    eth_totals = []
    p2s_totals = []
    for mev_type, stats in mev_by_type.items():
        types.append(mev_type.replace("_", " ").title())
        eth_totals.append(stats["ethereum"]["total"])
        p2s_totals.append(stats["p2s"]["total"])

    fig, ax = plt.subplots(figsize=(10, 7))
    x = np.arange(len(types))
    w = 0.38
    ax.bar(x - w / 2, eth_totals, w, label="Ethereum", color=COLOR_ETH, edgecolor="white", linewidth=1.2)
    ax.bar(x + w / 2, p2s_totals, w, label="P2S", color=COLOR_P2S, edgecolor="white", linewidth=1.2)
    ax.set_ylabel("Total MEV (ETH)", fontsize=FS_LABEL, fontweight='bold')
    ax.set_xticks(x)
    ax.set_xticklabels(types, rotation=25, ha="right", fontsize=FS_TICK)
    ax.tick_params(labelsize=FS_TICK)
    ax.legend(fontsize=FS_LEGEND, loc='upper right')
    sns.despine(ax=ax)
    ax.grid(True, alpha=0.18, linestyle="--", color="gray")
    ax.set_axisbelow(True)
    plt.tight_layout()
    os.makedirs(FIGURES_DIR, exist_ok=True)
    plt.savefig(out_path, dpi=300, bbox_inches="tight")
    plt.show()
    plt.close()
    print(f"Saved {out_path}")


def plot_mev_reduction(comparison_data: dict, out_path: str) -> None:
    """Horizontal bar chart: P2S MEV reduction % vs Ethereum by type."""
    mev_by_type = comparison_data.get("mev_by_type", {})
    if not mev_by_type:
        return

    sns.set_theme(style="ticks")
    types = []
    reductions = []
    for mev_type, stats in mev_by_type.items():
        types.append(mev_type.replace("_", " ").title())
        reductions.append(stats["reduction"]["total_pct"])

    fig, ax = plt.subplots(figsize=(10, 7))
    colors = [COLOR_P2S if r > 0 else COLOR_ETH for r in reductions]
    ax.barh(types, reductions, height=0.68, color=colors, edgecolor="white", linewidth=1.2)
    ax.set_xlabel("Reduction (%)", fontsize=FS_LABEL, fontweight='bold')
    ax.tick_params(labelsize=FS_TICK)
    sns.despine(ax=ax)
    ax.grid(True, alpha=0.18, linestyle="--", color="gray")
    ax.set_axisbelow(True)
    plt.tight_layout()
    os.makedirs(FIGURES_DIR, exist_ok=True)
    plt.savefig(out_path, dpi=300, bbox_inches="tight")
    plt.show()
    plt.close()
    print(f"Saved {out_path}")


def plot_activities_count(comparison_data: dict, out_path: str) -> None:
    """Bar chart: activity counts (miner payments, swaps, arbitrages, sandwich) Eth vs P2S."""
    sns.set_theme(style="ticks")
    comp = comparison_data.get("comparison", {})
    eth = comp.get("ethereum", {})
    p2s = comp.get("p2s", {})

    keys = ["miner_payments", "swaps", "arbitrages", "sandwich_attacks"]
    labels = [k.replace("_", " ").title() for k in keys]
    eth_vals = [eth.get(k, 0) for k in keys]
    p2s_vals = [p2s.get(k, 0) for k in keys]

    fig, ax = plt.subplots(figsize=(10, 7))
    x = np.arange(len(labels))
    w = 0.38
    ax.bar(x - w / 2, eth_vals, w, label="Ethereum", color=COLOR_ETH, edgecolor="white", linewidth=1.2)
    ax.bar(x + w / 2, p2s_vals, w, label="P2S", color=COLOR_P2S, edgecolor="white", linewidth=1.2)
    ax.set_ylabel("Count", fontsize=FS_LABEL, fontweight='bold')
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=25, ha="right", fontsize=FS_TICK)
    ax.tick_params(labelsize=FS_TICK)
    ax.legend(fontsize=FS_LEGEND, loc='upper right')
    sns.despine(ax=ax)
    ax.grid(True, alpha=0.18, linestyle="--", color="gray")
    ax.set_axisbelow(True)
    plt.tight_layout()
    os.makedirs(FIGURES_DIR, exist_ok=True)
    plt.savefig(out_path, dpi=300, bbox_inches="tight")
    plt.show()
    plt.close()
    print(f"Saved {out_path}")


def main():
    # Resolve paths from repo root (parent of plots/)
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    data_dir = os.path.join(repo_root, DATA_DIR)
    figures_dir = os.path.join(repo_root, FIGURES_DIR)

    data = load_comparison(data_dir)
    if not data:
        print("No MEV comparison data found. Put data/mev_comparison.json (or mev_comparison_*.json) in project root.", file=sys.stderr)
        sys.exit(1)

    plot_mev_totals(data, os.path.join(figures_dir, "mev_totals_by_type.pdf"))
    plot_mev_reduction(data, os.path.join(figures_dir, "mev_by_type.pdf"))
    plot_activities_count(data, os.path.join(figures_dir, "mev_activities_count.pdf"))
    print("Done. Figures in", figures_dir)


if __name__ == "__main__":
    main()
