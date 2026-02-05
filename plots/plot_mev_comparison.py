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

# Colors from seaborn vlag palette (diverging blue to red)
VLAG_PALETTE = sns.color_palette("vlag", n_colors=10)
COLOR_BLUE = VLAG_PALETTE[1]   # Ethereum (blue end)
COLOR_RED = VLAG_PALETTE[-2]   # P2S (red end)

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

    fig, ax = plt.subplots(figsize=(8, 5))
    x = np.arange(len(types))
    w = 0.35
    ax.bar(x - w / 2, eth_totals, w, label="Ethereum", color=COLOR_BLUE, edgecolor="white", linewidth=1.2)
    ax.bar(x + w / 2, p2s_totals, w, label="P2S", color=COLOR_RED, edgecolor="white", linewidth=1.2)
    ax.set_ylabel("Total MEV (ETH)", fontsize=14)
    ax.set_xticks(x)
    ax.set_xticklabels(types, rotation=25, ha="right", fontsize=13)
    ax.tick_params(axis='y', labelsize=12)
    ax.legend(fontsize=12)
    sns.despine(ax=ax)
    plt.tight_layout()
    os.makedirs(FIGURES_DIR, exist_ok=True)
    plt.savefig(out_path, dpi=300, bbox_inches="tight")
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

    fig, ax = plt.subplots(figsize=(8, 5))
    colors = [COLOR_RED if r > 0 else COLOR_BLUE for r in reductions]
    ax.barh(types, reductions, color=colors, edgecolor="white", linewidth=1.2)
    ax.set_xlabel("Reduction (%)", fontsize=14)
    ax.axvline(0, color="gray", linewidth=0.8, linestyle="--")
    ax.tick_params(axis='both', labelsize=12)
    sns.despine(ax=ax)
    plt.tight_layout()
    os.makedirs(FIGURES_DIR, exist_ok=True)
    plt.savefig(out_path, dpi=300, bbox_inches="tight")
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

    fig, ax = plt.subplots(figsize=(8, 5))
    x = np.arange(len(labels))
    w = 0.35
    ax.bar(x - w / 2, eth_vals, w, label="Ethereum", color=COLOR_BLUE, edgecolor="white", linewidth=1.2)
    ax.bar(x + w / 2, p2s_vals, w, label="P2S", color=COLOR_RED, edgecolor="white", linewidth=1.2)
    ax.set_ylabel("Count", fontsize=14)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=25, ha="right", fontsize=13)
    ax.tick_params(axis='y', labelsize=12)
    ax.legend(fontsize=12)
    sns.despine(ax=ax)
    plt.tight_layout()
    os.makedirs(FIGURES_DIR, exist_ok=True)
    plt.savefig(out_path, dpi=300, bbox_inches="tight")
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

    plot_mev_totals(data, os.path.join(figures_dir, "mev_totals_by_type.png"))
    plot_mev_reduction(data, os.path.join(figures_dir, "mev_by_type.png"))
    plot_activities_count(data, os.path.join(figures_dir, "mev_activities_count.png"))
    print("Done. Figures in", figures_dir)


if __name__ == "__main__":
    main()
