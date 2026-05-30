#!/usr/bin/env python3
"""
MEV comparison plots (Ethereum vs P2S).
Uses a single cached comparison dataset in data/ — no testnet rerun required.

Also reports a bootstrap 95% CI and Mann-Whitney U p-value on the headline MEV
reduction, using the per-block extracted-MEV vectors written by simulator.py
into data/mev_comparison.json under "per_block_gain_eth".
"""

import glob
import json
import os
import sys

import matplotlib.pyplot as plt
import numpy as np
import seaborn as sns
from scipy import stats

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

_LABEL_MAP = {
    "Miner Payments":  "Gas Reward",
    "Sandwich Attacks": "Sandwich",
}

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


def _plot_dumbbell(labels, eth_values, p2s_values, xlabel, out_path,
                   value_fmt="{:.2f}", log_x=False) -> None:
    """Connected-dot (dumbbell) chart: one row per category, two dots per row.

    Used in place of side-by-side bar charts to make the magnitude of each
    PoS→P2S drop visually obvious. Each row connects the Ethereum-PoS value
    to the P2S value with a thin gray line; the two dots are coloured by
    protocol palette.
    """
    sns.set_theme(style="ticks")
    n = len(labels)
    fig_h = max(3.5, 0.95 * n + 1.6)
    fig, ax = plt.subplots(figsize=(10, fig_h))

    y = np.arange(n)
    # connecting segments (drawn under the dots)
    for yi, e, p in zip(y, eth_values, p2s_values):
        ax.plot([e, p], [yi, yi], color="gray", lw=2.0, alpha=0.55, zorder=1)
    # dots: PoS larger to match the visual weight of the active values
    ax.scatter(eth_values, y, s=240, color=COLOR_ETH, label="Ethereum PoS",
               zorder=3, edgecolor="white", linewidth=1.6)
    ax.scatter(p2s_values, y, s=240, color=COLOR_P2S, label="P2S",
               zorder=3, edgecolor="white", linewidth=1.6)
    # Single label per row, placed in a clear column on the right of the data,
    # showing the magnitude of the PoS→P2S drop. This avoids labels overlapping
    # the dots themselves.
    vmax = max(max(eth_values), max(p2s_values), 1e-9)
    vmin = min(min(eth_values), min(p2s_values), 0)
    label_x = vmax + 0.06 * (vmax - vmin)
    for yi, e, p in zip(y, eth_values, p2s_values):
        delta = e - p
        # for blind-planting style rows where p > e, show "+x" to indicate P2S residual
        sign = "" if delta >= 0 else "+"
        ax.annotate(f"{sign}{value_fmt.format(abs(delta))}",
                    xy=(label_x, yi),
                    ha="left", va="center",
                    fontsize=FS_TICK - 2, fontweight="bold",
                    color="black", alpha=0.75)

    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontsize=FS_TICK)
    ax.set_xlabel(xlabel, fontsize=FS_LABEL, fontweight="bold")
    ax.tick_params(labelsize=FS_TICK)
    if log_x:
        ax.set_xscale("symlog", linthresh=0.01)
    # Legend goes above the plot to avoid colliding with the delta-label
    # column on the right (which always sits in the bottom-right area).
    ax.legend(fontsize=FS_LEGEND, loc="lower center",
              bbox_to_anchor=(0.5, 1.02), ncol=2, frameon=False)
    ax.grid(True, axis="x", alpha=0.18, linestyle="--", color="gray")
    ax.set_axisbelow(True)
    # x-limits include space on the right for the delta-label column
    pad_left  = 0.05 * (vmax - vmin + 1e-9)
    pad_right = 0.22 * (vmax - vmin + 1e-9)
    ax.set_xlim(vmin - pad_left, vmax + pad_right)
    sns.despine(ax=ax, left=True)
    ax.invert_yaxis()  # first row at top
    plt.tight_layout()
    os.makedirs(FIGURES_DIR, exist_ok=True)
    plt.savefig(out_path, dpi=300, bbox_inches="tight")
    plt.close()
    print(f"Saved {out_path}")


def plot_mev_totals(comparison_data: dict, out_path: str) -> None:
    """Dumbbell plot of total MEV (ETH) per attack type.

    Block stuffing is excluded because the reservation fee makes it
    unprofitable at all positive φ (Proposition 3); both endpoints would be
    zero and add visual noise. The accompanying prose explains the
    elimination directly.
    """
    mev_by_type = comparison_data.get("mev_by_type", {})
    if not mev_by_type:
        return

    # Display order: highest-Ethereum-MEV first (matches the visual story).
    candidates = [(k, v) for k, v in mev_by_type.items() if k != "block_stuffing"]
    candidates.sort(key=lambda kv: kv[1]["ethereum"]["total"], reverse=True)

    labels, eth_vals, p2s_vals = [], [], []
    for mev_type, stats in candidates:
        raw = mev_type.replace("_", " ").title()
        labels.append(_LABEL_MAP.get(raw, raw))
        eth_vals.append(stats["ethereum"]["total"])
        p2s_vals.append(stats["p2s"]["total"])

    _plot_dumbbell(labels, eth_vals, p2s_vals,
                   xlabel="Total MEV extracted (ETH)",
                   out_path=out_path,
                   value_fmt="{:.2f}")


def plot_mev_reduction(comparison_data: dict, out_path: str) -> None:
    """Horizontal bar chart: P2S MEV reduction % vs Ethereum by type."""
    mev_by_type = comparison_data.get("mev_by_type", {})
    if not mev_by_type:
        return

    sns.set_theme(style="ticks")
    types = []
    reductions = []
    for mev_type, stats in mev_by_type.items():
        raw = mev_type.replace("_", " ").title()
        types.append(_LABEL_MAP.get(raw, raw))
        reductions.append(stats["reduction"]["total_pct"])

    fig, ax = plt.subplots(figsize=(10, 7))
    colors = [COLOR_P2S if r > 0 else COLOR_ETH for r in reductions]
    ax.barh(types, reductions, height=0.68, color=colors, edgecolor="white", linewidth=1.2)
    ax.set_xlabel("Reduction (%)", fontsize=FS_LABEL, fontweight='bold')
    ax.tick_params(labelsize=FS_LABEL)
    sns.despine(ax=ax)
    ax.grid(True, alpha=0.18, linestyle="--", color="gray")
    ax.set_axisbelow(True)
    plt.tight_layout()
    os.makedirs(FIGURES_DIR, exist_ok=True)
    plt.savefig(out_path, dpi=300, bbox_inches="tight")
    plt.close()
    print(f"Saved {out_path}")


def plot_activities_count(comparison_data: dict, out_path: str) -> None:
    """Dumbbell plot of successful-attack counts per strategy (PoS vs P2S).

    Definitions (one row per strategy):
      * Front-running: blocks containing a successful priority-gas-auction
        front-run, i.e.\ attacker tx executed before the target swap.
      * Sandwich: blocks containing a successful sandwich (attacker tx both
        before and after target).
      * Arbitrage: blocks containing a successful cross-DEX arbitrage that
        depended on observing the target pool state pre-execution.
      * Blind planting: blocks where a speculative P2S \\ac{pht} (no content
        visibility) was reserved and the matching MT was profitably revealed.

    Each row's two dots show the number of blocks (out of `num_blocks`) in
    which the strategy succeeded under PoS and under P2S.

    Source: `mev_by_type[strategy]["ethereum"|"p2s"]["count"]` in
    data/mev_comparison.json, which is the exact `successes` count recorded
    by `MEVAttackStrategies` in simulator.py. We do not use the misleading
    aggregate `comparison.ethereum.swaps` / `sandwich_attacks` fields whose
    semantics differ between the two protocols.
    """
    mev_by_type = comparison_data.get("mev_by_type", {})
    if not mev_by_type:
        return

    # Display order: Ethereum-active strategies first, then P2S residual.
    candidates = [(k, v) for k, v in mev_by_type.items() if k != "block_stuffing"]
    candidates.sort(key=lambda kv: kv[1]["ethereum"]["count"], reverse=True)

    labels, eth_vals, p2s_vals = [], [], []
    for mev_type, stats in candidates:
        raw = mev_type.replace("_", " ").title()
        labels.append(_LABEL_MAP.get(raw, raw))
        eth_vals.append(int(stats["ethereum"]["count"]))
        p2s_vals.append(int(stats["p2s"]["count"]))

    n_blocks = comparison_data.get("metadata", {}).get("num_blocks")
    n_blocks = n_blocks or comparison_data.get("comparison", {}).get("ethereum", {}).get("total_blocks", 1000)
    _plot_dumbbell(labels, eth_vals, p2s_vals,
                   xlabel=f"Successful attacks per {n_blocks:,} blocks",
                   out_path=out_path,
                   value_fmt="{:.0f}")


def bootstrap_reduction_ci(
    eth_per_block: np.ndarray,
    p2s_per_block: np.ndarray,
    n_boot: int = 10_000,
    seed: int = 42,
) -> dict:
    """
    Bootstrap 95% CI for the percentage MEV reduction
        reduction_pct = (E[MEV_eth] - E[MEV_p2s]) / E[MEV_eth] * 100

    Per-block vectors are resampled independently with replacement (paired
    by block index is not assumed because the attacker draws are independent
    Bernoulli trials per block).  Also reports the point estimate and a
    Mann-Whitney U two-sided p-value on per-block MEV.
    """
    rng = np.random.default_rng(seed)
    n_eth = len(eth_per_block)
    n_p2s = len(p2s_per_block)
    if n_eth == 0 or n_p2s == 0:
        return {"point": float("nan"), "ci_lower": float("nan"),
                "ci_upper": float("nan"), "p_mw": float("nan"),
                "n_boot": n_boot, "n_eth": n_eth, "n_p2s": n_p2s,
                "eth_mean": 0.0, "p2s_mean": 0.0}

    eth_mean = float(eth_per_block.mean())
    p2s_mean = float(p2s_per_block.mean())
    point = ((eth_mean - p2s_mean) / eth_mean * 100.0) if eth_mean > 0 else 0.0

    reductions = np.empty(n_boot, dtype=float)
    eth_idx = rng.integers(0, n_eth, size=(n_boot, n_eth))
    p2s_idx = rng.integers(0, n_p2s, size=(n_boot, n_p2s))
    eth_means = eth_per_block[eth_idx].mean(axis=1)
    p2s_means = p2s_per_block[p2s_idx].mean(axis=1)
    valid = eth_means > 0
    reductions[valid]  = (eth_means[valid] - p2s_means[valid]) / eth_means[valid] * 100.0
    reductions[~valid] = 0.0

    ci_lower, ci_upper = np.percentile(reductions, [2.5, 97.5])

    # Mann-Whitney U: two-sided test that the two per-block distributions differ.
    try:
        mw = stats.mannwhitneyu(eth_per_block, p2s_per_block, alternative="two-sided")
        p_mw = float(mw.pvalue)
    except Exception:
        p_mw = float("nan")

    return {
        "point":     float(point),
        "ci_lower":  float(ci_lower),
        "ci_upper":  float(ci_upper),
        "p_mw":      p_mw,
        "n_boot":    n_boot,
        "n_eth":     n_eth,
        "n_p2s":     n_p2s,
        "eth_mean":  eth_mean,
        "p2s_mean":  p2s_mean,
    }


def report_headline_ci(data: dict) -> dict:
    """Compute and print headline reduction CI + Mann-Whitney p-value."""
    pb = (data or {}).get("per_block_gain_eth", {})
    eth = np.asarray(pb.get("ethereum", []), dtype=float)
    p2s = np.asarray(pb.get("p2s",      []), dtype=float)
    summary = bootstrap_reduction_ci(eth, p2s, n_boot=10_000)
    print("\n=== Headline MEV reduction (post-Merge economics) ===")
    print(f"  Per-block N (eth): {summary['n_eth']}   per-block N (p2s): {summary['n_p2s']}")
    print(f"  Mean MEV/block ETH:  eth={summary['eth_mean']:.6f}   "
          f"p2s={summary['p2s_mean']:.6f}")
    print(f"  Point reduction:     {summary['point']:.2f}%")
    print(f"  Bootstrap 95% CI:    [{summary['ci_lower']:.2f}%, {summary['ci_upper']:.2f}%]  "
          f"(B={summary['n_boot']})")
    print(f"  Mann-Whitney U p:    {summary['p_mw']:.3e}")
    return summary


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
    plot_activities_count(data, os.path.join(figures_dir, "mev_activities_count.pdf"))
    report_headline_ci(data)
    print("Done. Figures in", figures_dir)


if __name__ == "__main__":
    main()
