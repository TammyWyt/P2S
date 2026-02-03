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

# Pastel palette: Ethereum = soft blue, P2S = soft green
PASTEL_ETH = "#9ECAE1"
PASTEL_P2S = "#A1D99B"
PASTEL_REDUCTION = "#C7E9C0"
PASTEL_NEUTRAL = "#D9D9D9"

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


def plot_mev_summary(comparison_data: dict, out_path: str) -> None:
    """Single figure: Total MEV by type (Eth vs P2S) and reduction %."""
    mev_by_type = comparison_data.get("mev_by_type", {})
    if not mev_by_type:
        return

    sns.set_theme(style="whitegrid", palette="pastel")
    types = []
    eth_totals = []
    p2s_totals = []
    reductions = []
    for mev_type, stats in mev_by_type.items():
        types.append(mev_type.replace("_", " ").title())
        eth_totals.append(stats["ethereum"]["total"])
        p2s_totals.append(stats["p2s"]["total"])
        reductions.append(stats["reduction"]["total_pct"])

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 5))

    x = np.arange(len(types))
    w = 0.35
    ax1.bar(x - w / 2, eth_totals, w, label="Ethereum", color=PASTEL_ETH, edgecolor="white", linewidth=1.2)
    ax1.bar(x + w / 2, p2s_totals, w, label="P2S", color=PASTEL_P2S, edgecolor="white", linewidth=1.2)
    ax1.set_ylabel("Total MEV (ETH)")
    ax1.set_title("MEV by type")
    ax1.set_xticks(x)
    ax1.set_xticklabels(types, rotation=25, ha="right")
    ax1.legend()
    sns.despine(ax=ax1, left=False, bottom=False)

    reduction_colors = [PASTEL_REDUCTION if r > 0 else PASTEL_NEUTRAL for r in reductions]
    ax2.barh(types, reductions, color=reduction_colors, edgecolor="white", linewidth=1.2)
    ax2.set_xlabel("Reduction (%)")
    ax2.set_title("P2S MEV reduction vs Ethereum")
    ax2.axvline(0, color="gray", linewidth=0.8, linestyle="--")
    sns.despine(ax=ax2, left=False, bottom=False)

    fig.suptitle("MEV comparison: Ethereum vs P2S", fontsize=14, fontweight="bold", y=1.02)
    plt.tight_layout()
    os.makedirs(FIGURES_DIR, exist_ok=True)
    plt.savefig(out_path, dpi=300, bbox_inches="tight")
    plt.close()
    print(f"Saved {out_path}")


def plot_activities_count(comparison_data: dict, out_path: str) -> None:
    """Bar chart: activity counts (miner payments, swaps, arbitrages, sandwich) Eth vs P2S."""
    sns.set_theme(style="whitegrid", palette="pastel")
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
    ax.bar(x - w / 2, eth_vals, w, label="Ethereum", color=PASTEL_ETH, edgecolor="white", linewidth=1.2)
    ax.bar(x + w / 2, p2s_vals, w, label="P2S", color=PASTEL_P2S, edgecolor="white", linewidth=1.2)
    ax.set_ylabel("Count")
    ax.set_title("MEV activity counts: Ethereum vs P2S")
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=25, ha="right")
    ax.legend()
    sns.despine(ax=ax, left=False, bottom=False)
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

    plot_mev_summary(data, os.path.join(figures_dir, "mev_by_type.png"))
    plot_activities_count(data, os.path.join(figures_dir, "mev_activities_count.png"))
    print("Done. Figures in", figures_dir)


if __name__ == "__main__":
    main()
