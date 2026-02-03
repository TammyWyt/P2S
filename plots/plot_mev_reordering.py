#!/usr/bin/env python3
"""
MEV reordering: mean MEV opportunity per block (P2S vs Ethereum PoS).
Uses a single cached dataset in data/ — no simulation rerun required.
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

# Pastel palette
PASTEL_P2S = "#A1D99B"
PASTEL_ETH = "#9ECAE1"


def load_reordering_data(data_dir: str):
    """Load one dataset: data/mev_reordering.json or latest data/simulation_*.json."""
    single = os.path.join(data_dir, "mev_reordering.json")
    if os.path.isfile(single):
        with open(single, "r") as f:
            return json.load(f)
    files = glob.glob(os.path.join(data_dir, "simulation_*.json"))
    if not files:
        return None
    path = max(files, key=os.path.getmtime)
    with open(path, "r") as f:
        return json.load(f)


def plot_mev_reordering(data: dict, out_path: str) -> None:
    """Single bar chart: mean MEV opportunity per block."""
    sns.set_theme(style="whitegrid", palette="pastel")
    reorder = data.get("mev_reordering", {})
    protocols = ["p2s", "ethereum_pos"]
    labels = ["P2S", "Ethereum PoS"]
    colors = [PASTEL_P2S, PASTEL_ETH]

    means = []
    stds = []
    for p in protocols:
        opps = reorder.get(p, {}).get("opportunities", [])
        means.append(float(np.mean(opps)) if opps else 0)
        stds.append(float(np.std(opps)) if len(opps) > 1 else 0)

    fig, ax = plt.subplots(figsize=(6, 4))
    ax.bar(labels, means, color=colors, yerr=stds, capsize=8, edgecolor="white", linewidth=1.2)
    ax.set_ylabel("Mean MEV opportunity per block (ETH)")
    ax.set_title("MEV reordering opportunity: P2S vs Ethereum PoS", fontweight="bold")
    ax.set_ylim(0, max(means) * 1.2 if means else 1)
    sns.despine(ax=ax, left=False, bottom=False)
    plt.tight_layout()
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    plt.savefig(out_path, dpi=300, bbox_inches="tight")
    plt.close()
    print(f"Saved {out_path}")


def main():
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    data_dir = os.path.join(repo_root, DATA_DIR)
    figures_dir = os.path.join(repo_root, FIGURES_DIR)

    data = load_reordering_data(data_dir)
    if not data:
        print("No data. Add data/mev_reordering.json or data/simulation_*.json", file=sys.stderr)
        sys.exit(1)

    plot_mev_reordering(data, os.path.join(figures_dir, "mev_reordering.png"))
    print("Done. Figures in", figures_dir)


if __name__ == "__main__":
    main()
