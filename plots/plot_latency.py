#!/usr/bin/env python3
"""
Network latency comparison: P2S vs Ethereum PoS.

Runs the block simulator to obtain per-block timing data, then produces:

  latency_cdf.pdf       — CDF of total slot latency (all congestion levels pooled)
  latency_congestion.pdf — box plots of slot latency by block gas utilization %,
                           both protocols, with bootstrap 95 % CI on the median.
  latency_breakdown.pdf  — stacked mean phase time, P2S vs PoS

All timing comes from simulate_network_delay() in simulator.py using the real
Blockscout gas-price trace.  No synthetic values are hard-coded in this script.

The historical "Congestion level" multiplier is mapped to block gas-utilization
% (50 % = EIP-1559 target) via P2SSimulator._congestion_to_block_fill().  This
is the labelling change that makes the x-axis an Ethereum observable rather than
an undocumented synthetic parameter.
"""

import os
import sys
import random

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
import numpy as np
import pandas as pd
import seaborn as sns

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

import time as _time_mod
_time_mod.sleep = lambda _: None   # skip simulator sleep() calls; timing values are pre-computed

from scripts.simulation.simulator import P2SSimulator

FIGURES_DIR = os.path.join(_REPO, "figures")

# Bump from 800 → 2500: 500 blocks per congestion bucket gives stable quartiles.
N_BLOCKS_PER_BUCKET = 500
CONGESTION_LEVELS = [0.0, 0.1, 0.3, 0.5, 0.7]
N_BLOCKS = N_BLOCKS_PER_BUCKET * len(CONGESTION_LEVELS)

# Bootstrap parameters for median CIs
N_BOOTSTRAP = 10_000
BOOT_SEED   = 42

FS_LABEL  = 22
FS_TICK   = 18
FS_LEGEND = 16

# Palette: consistent with plot_welfare.py and plot_phi_sweep.py
_DEEP = sns.color_palette("deep")
COL_P2S = _DEEP[0]   # steel blue  — P2S  (matches welfare/phi_sweep)
COL_POS = _DEEP[3]   # red-orange  — Ethereum PoS (matches plot_welfare.py)

# Gas-utilization % labels mapped 1-to-1 with CONGESTION_LEVELS via
# P2SSimulator._congestion_to_block_fill().
GAS_UTIL_PCT = [int(round(P2SSimulator._congestion_to_block_fill(c) * 100))
                for c in CONGESTION_LEVELS]


def _bootstrap_ci(values: np.ndarray, statistic=np.median,
                  n_boot: int = N_BOOTSTRAP, seed: int = BOOT_SEED) -> tuple:
    """Return (point, lo, hi) where lo/hi is the 95% bootstrap CI."""
    if len(values) == 0:
        return float("nan"), float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    n   = len(values)
    idx = rng.integers(0, n, size=(n_boot, n))
    stats_boot = statistic(values[idx], axis=1)
    lo, hi = np.percentile(stats_boot, [2.5, 97.5])
    return float(statistic(values)), float(lo), float(hi)


def run_sim():
    """Force a uniform mix of CONGESTION_LEVELS so each bucket has N_BLOCKS_PER_BUCKET blocks.

    The simulator normally picks congestion levels uniformly at random; for a
    box-plot we want exactly the same number of blocks per bucket to stabilise
    the per-bucket quartiles.
    """
    print(f"Running simulator ({N_BLOCKS} blocks, {N_BLOCKS_PER_BUCKET}/bucket) …")
    sim = P2SSimulator()

    # Build a flat sequence of congestion values: bucket-balanced, shuffled order.
    seq = []
    for c in CONGESTION_LEVELS:
        seq.extend([c] * N_BLOCKS_PER_BUCKET)
    rng = random.Random(BOOT_SEED)
    rng.shuffle(seq)

    # Monkey-patch random.choice on the simulator's congestion picker via a
    # deterministic iterator.  The simulator calls random.choice(congestion_levels);
    # we intercept by patching random.choice for the duration of run_simulation.
    import random as _rng
    seq_iter = iter(seq)
    original_choice = _rng.choice
    _rng_congestion_set = set(CONGESTION_LEVELS)

    def _patched_choice(population):
        try:
            pop_set = set(population)
        except TypeError:
            return original_choice(population)
        if pop_set == _rng_congestion_set:
            try:
                return next(seq_iter)
            except StopIteration:
                return original_choice(population)
        return original_choice(population)

    _rng.choice = _patched_choice
    try:
        sim.run_simulation(N_BLOCKS)
    finally:
        _rng.choice = original_choice

    p2s  = sim.results['p2s_data']
    pos  = sim.results['ethereum_pos_data']
    print(f"  collected {len(p2s)} P2S blocks, {len(pos)} PoS blocks")
    return p2s, pos


# ── Figure 1: Latency CDF ─────────────────────────────────────────────────────

def plot_cdf(p2s, pos, out_path):
    p2s_lat = np.array([b['network_latency'] for b in p2s])
    pos_lat = np.array([b['network_latency'] for b in pos])

    sns.set_theme(style="ticks")
    fig, ax = plt.subplots(figsize=(9, 5))

    for lat, label, col, ls in [
        (p2s_lat, "P2S",          COL_P2S, "-"),
        (pos_lat, "Ethereum PoS", COL_POS, "--"),
    ]:
        sorted_lat = np.sort(lat)
        cdf = np.arange(1, len(sorted_lat) + 1) / len(sorted_lat)
        ax.plot(sorted_lat, cdf, label=label, color=col, lw=2.2, linestyle=ls)

    # mark p50 and p95
    for lat, col in [(p2s_lat, COL_P2S), (pos_lat, COL_POS)]:
        for pct, ls in [(50, ":"), (95, "--")]:
            val = np.percentile(lat, pct)
            ax.axvline(val, color=col, lw=0.8, linestyle=ls, alpha=0.5)

    ax.set_xlabel("Slot network latency (s)", fontsize=FS_LABEL, fontweight="bold")
    ax.set_ylabel("CDF", fontsize=FS_LABEL, fontweight="bold")
    ax.set_ylim(0, 1.05)
    ax.tick_params(labelsize=FS_TICK)
    ax.legend(fontsize=FS_LEGEND)
    ax.grid(True, alpha=0.18, linestyle="--", color="gray")
    ax.set_axisbelow(True)
    sns.despine(ax=ax)
    plt.tight_layout()
    plt.savefig(out_path, dpi=300, bbox_inches="tight")
    plt.close()
    print(f"Saved {out_path}")


# ── Figure 2: Box plots of latency by congestion level ───────────────────────
# Inspired by Javed & Mangues-Bafalluy (2025): box plots with overall-mean
# reference lines make the full per-level distribution visible rather than
# just the median+IQR band.

def plot_by_congestion(p2s, pos, out_path):
    # Map each block's congestion_level → block gas-utilization %.
    def _gas_util_label(c: float) -> str:
        return f"{int(round(P2SSimulator._congestion_to_block_fill(c) * 100))}%"

    records = []
    for b in p2s:
        c = b["congestion_level"]
        if any(abs(c - cl) < 1e-9 for cl in CONGESTION_LEVELS):
            records.append({"GasUtil": _gas_util_label(c),
                            "Latency (s)": b["network_latency"],
                            "Protocol": "P2S"})
    for b in pos:
        c = b["congestion_level"]
        if any(abs(c - cl) < 1e-9 for cl in CONGESTION_LEVELS):
            records.append({"GasUtil": _gas_util_label(c),
                            "Latency (s)": b["network_latency"],
                            "Protocol": "Ethereum PoS"})

    df = pd.DataFrame(records)
    order = [f"{u}%" for u in GAS_UTIL_PCT]

    sns.set_theme(style="ticks")
    fig, ax = plt.subplots(figsize=(10, 5))

    palette = {"P2S": COL_P2S, "Ethereum PoS": COL_POS}
    sns.boxplot(data=df, x="GasUtil", y="Latency (s)", hue="Protocol",
                order=order, palette=palette, linewidth=1.8,
                fliersize=3, width=0.6, ax=ax)

    # overall-mean reference lines (dashed)
    means = {}
    for protocol, col in [("P2S", COL_P2S), ("Ethereum PoS", COL_POS)]:
        means[protocol] = df[df["Protocol"] == protocol]["Latency (s)"].mean()
        ax.axhline(means[protocol], color=col, lw=1.8, linestyle="--", alpha=0.55)

    legend_handles = [
        Patch(facecolor=COL_P2S, edgecolor="k", linewidth=0.5, label="P2S"),
        Patch(facecolor=COL_POS, edgecolor="k", linewidth=0.5, label="Ethereum PoS"),
        Line2D([0], [0], color=COL_P2S, lw=1.8, linestyle="--",
               label=f"P2S mean ({means['P2S']:.2f} s)"),
        Line2D([0], [0], color=COL_POS, lw=1.8, linestyle="--",
               label=f"PoS mean ({means['Ethereum PoS']:.2f} s)"),
    ]
    ax.legend(handles=legend_handles, fontsize=FS_LEGEND - 2, ncol=2)
    ax.get_legend().set_title(None)

    ax.set_xlabel("Block gas utilization (%)", fontsize=FS_LABEL, fontweight="bold")
    ax.set_ylabel("Slot network latency (s)", fontsize=FS_LABEL, fontweight="bold")
    ax.tick_params(labelsize=FS_TICK)
    ax.grid(True, alpha=0.18, linestyle="--", color="gray")
    ax.set_axisbelow(True)
    sns.despine(ax=ax)
    plt.tight_layout()
    plt.savefig(out_path, dpi=300, bbox_inches="tight")
    plt.close()
    print(f"Saved {out_path}")

    # ── Per-bucket bootstrap 95 % CI on the median latency overhead ──────────
    print("\n=== Median slot latency by gas utilization (with 95% bootstrap CI) ===")
    print(f"{'GasUtil':>8} {'Protocol':>14} {'median(s)':>10} {'95% CI lower':>14} {'95% CI upper':>14}")
    for util, c in zip(GAS_UTIL_PCT, CONGESTION_LEVELS):
        for protocol, col in [("P2S", COL_P2S), ("Ethereum PoS", COL_POS)]:
            vals = df[(df["Protocol"] == protocol) &
                      (df["GasUtil"] == f"{util}%")]["Latency (s)"].to_numpy()
            point, lo, hi = _bootstrap_ci(vals, statistic=np.median)
            print(f"{util:>7}% {protocol:>14} {point:>10.4f} {lo:>14.4f} {hi:>14.4f}")


# ── Figure 3: Phase breakdown (stacked bar) ───────────────────────────────────

def plot_phase_breakdown(p2s, pos, out_path):
    # NOTE on phase semantics:
    # The simulator records `pht_time` and `mt_time` as SUMs over all transactions
    # in the block (parallelizable client-side work, not serial slot time).  Their
    # actual contribution to slot latency is capped at the simulator's
    # `time.sleep(min(x, 0.1))` cap because the work happens in parallel across
    # users.  We replicate that cap here so the stacked bar reflects real slot
    # contribution rather than raw per-transaction sums.
    PHT_CAP = 0.1
    MT_CAP  = 0.1
    MEM_CAP = 0.05

    p2s_b1  = np.mean([b['b1_time']  for b in p2s])
    p2s_b2  = np.mean([b['b2_time']  for b in p2s])
    p2s_pht = np.mean([min(b['pht_time'], PHT_CAP) for b in p2s])
    p2s_mt  = np.mean([min(b['mt_time'],  MT_CAP)  for b in p2s])

    pos_mem  = np.mean([min(b['mempool_time'], MEM_CAP) for b in pos])
    pos_prop = np.mean([b['proposal_time']     for b in pos])
    pos_conf = np.mean([b['confirmation_time'] for b in pos])

    sns.set_theme(style="ticks")
    fig, ax = plt.subplots(figsize=(8, 5))

    protocols  = ["P2S", "Ethereum PoS"]
    bar_width  = 0.45
    x          = np.array([0, 1])

    # P2S stack: shades of the P2S blue
    p2s_phases = [p2s_pht, p2s_b1, p2s_mt, p2s_b2]
    p2s_labels = ["PHT creation", "B1 propagation", "MT reveal", "B2 propagation"]
    p2s_colors = sns.light_palette(COL_P2S, n_colors=6)[2:]   # 4 shades, lightest first

    # PoS stack: shades of the PoS red-orange
    pos_phases = [pos_mem, pos_prop, pos_conf]
    pos_labels = ["Mempool processing", "Block proposal", "Confirmation"]
    pos_colors = sns.light_palette(COL_POS, n_colors=5)[2:]    # 3 shades, lightest first

    bottom = 0.0
    for val, lbl, col in zip(p2s_phases, p2s_labels, p2s_colors):
        ax.bar(x[0], val, bar_width, bottom=bottom, color=col, label=lbl, edgecolor="white")
        bottom += val

    bottom = 0.0
    for val, lbl, col in zip(pos_phases, pos_labels, pos_colors):
        ax.bar(x[1], val, bar_width, bottom=bottom, color=col, label=lbl, edgecolor="white")
        bottom += val

    ax.set_xticks(x)
    ax.set_xticklabels(protocols, fontsize=FS_TICK)
    ax.set_ylabel("Mean latency (s)", fontsize=FS_LABEL, fontweight="bold")
    ax.tick_params(labelsize=FS_TICK)
    # Legend outside the plot area so it doesn't overlap the bars.
    ax.legend(fontsize=FS_LEGEND - 2, loc="center left",
              bbox_to_anchor=(1.02, 0.5), ncol=1, frameon=False)
    ax.grid(axis="y", alpha=0.18, linestyle="--", color="gray")
    ax.set_axisbelow(True)
    sns.despine(ax=ax)
    plt.tight_layout()
    plt.savefig(out_path, dpi=300, bbox_inches="tight")
    plt.close()
    print(f"Saved {out_path}")


def _overall_overhead_ci(p2s, pos) -> None:
    """Report bootstrap CI on overall P2S, PoS, and overhead (P2S - PoS) medians."""
    p2s_lat = np.array([b["network_latency"] for b in p2s])
    pos_lat = np.array([b["network_latency"] for b in pos])

    p2s_med, p2s_lo, p2s_hi = _bootstrap_ci(p2s_lat, statistic=np.median)
    pos_med, pos_lo, pos_hi = _bootstrap_ci(pos_lat, statistic=np.median)

    # Overhead = median(P2S) - median(PoS), bootstrapped jointly.
    rng = np.random.default_rng(BOOT_SEED)
    n_p2s, n_pos = len(p2s_lat), len(pos_lat)
    overhead_samples = np.empty(N_BOOTSTRAP, dtype=float)
    for k in range(N_BOOTSTRAP):
        a = p2s_lat[rng.integers(0, n_p2s, n_p2s)]
        b = pos_lat[rng.integers(0, n_pos, n_pos)]
        overhead_samples[k] = np.median(a) - np.median(b)
    overhead_point = float(np.median(p2s_lat) - np.median(pos_lat))
    o_lo, o_hi = np.percentile(overhead_samples, [2.5, 97.5])

    print("\n=== Overall latency medians (95 % bootstrap CI) ===")
    print(f"  P2S    median: {p2s_med:.4f} s  [95% CI {p2s_lo:.4f}, {p2s_hi:.4f}]")
    print(f"  PoS    median: {pos_med:.4f} s  [95% CI {pos_lo:.4f}, {pos_hi:.4f}]")
    print(f"  Overhead (P2S − PoS) median: {overhead_point*1000:.1f} ms  "
          f"[95% CI {o_lo*1000:.1f}, {o_hi*1000:.1f}] ms")


def main():
    os.makedirs(FIGURES_DIR, exist_ok=True)
    p2s, pos = run_sim()

    plot_cdf(p2s, pos,
             os.path.join(FIGURES_DIR, "latency_cdf.pdf"))
    plot_by_congestion(p2s, pos,
                       os.path.join(FIGURES_DIR, "latency_congestion.pdf"))
    plot_phase_breakdown(p2s, pos,
                         os.path.join(FIGURES_DIR, "latency_breakdown.pdf"))
    _overall_overhead_ci(p2s, pos)


if __name__ == "__main__":
    main()
