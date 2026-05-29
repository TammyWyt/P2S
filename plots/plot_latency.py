#!/usr/bin/env python3
"""
Network latency comparison: P2S vs Ethereum PoS.

Runs the block simulator to obtain per-block timing data, then produces:

  latency_cdf.pdf       — CDF of total slot latency (all congestion levels pooled)
  latency_congestion.pdf — box plots of slot latency by congestion level, both protocols
  latency_breakdown.pdf  — stacked mean phase time, P2S vs PoS

All timing comes from simulate_network_delay() in simulator.py using the real
Blockscout gas-price trace.  No synthetic values are hard-coded in this script.
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
N_BLOCKS    = 800

FS_LABEL  = 22
FS_TICK   = 18
FS_LEGEND = 16

# Palette: consistent with plot_welfare.py and plot_phi_sweep.py
_DEEP = sns.color_palette("deep")
COL_P2S = _DEEP[0]   # steel blue  — P2S  (matches welfare/phi_sweep)
COL_POS = _DEEP[3]   # red-orange  — Ethereum PoS (matches plot_welfare.py)

CONGESTION_LEVELS = [0.0, 0.1, 0.3, 0.5, 0.7]


def run_sim():
    print(f"Running simulator ({N_BLOCKS} blocks) …")
    sim = P2SSimulator()
    sim.run_simulation(N_BLOCKS)
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
    records = []
    for b in p2s:
        c = b["congestion_level"]
        if any(abs(c - cl) < 1e-9 for cl in CONGESTION_LEVELS):
            records.append({"Congestion": f"{c:.1f}", "Latency (s)": b["network_latency"],
                            "Protocol": "P2S"})
    for b in pos:
        c = b["congestion_level"]
        if any(abs(c - cl) < 1e-9 for cl in CONGESTION_LEVELS):
            records.append({"Congestion": f"{c:.1f}", "Latency (s)": b["network_latency"],
                            "Protocol": "Ethereum PoS"})

    df = pd.DataFrame(records)
    # keep congestion labels in the order they appear in CONGESTION_LEVELS
    order = [f"{c:.1f}" for c in CONGESTION_LEVELS]

    sns.set_theme(style="ticks")
    fig, ax = plt.subplots(figsize=(10, 5))

    palette = {"P2S": COL_P2S, "Ethereum PoS": COL_POS}
    sns.boxplot(data=df, x="Congestion", y="Latency (s)", hue="Protocol",
                order=order, palette=palette, linewidth=1.8,
                fliersize=3, width=0.6, ax=ax)

    # overall-mean reference lines (dashed) — same idea as the red dashed line
    # in Javed & Mangues-Bafalluy Fig. 6
    means = {}
    for protocol, col in [("P2S", COL_P2S), ("Ethereum PoS", COL_POS)]:
        means[protocol] = df[df["Protocol"] == protocol]["Latency (s)"].mean()
        ax.axhline(means[protocol], color=col, lw=1.8, linestyle="--", alpha=0.55)

    # manual legend: protocol boxes + mean-line entries
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

    ax.set_xlabel("Congestion level", fontsize=FS_LABEL, fontweight="bold")
    ax.set_ylabel("Slot network latency (s)", fontsize=FS_LABEL, fontweight="bold")
    ax.tick_params(labelsize=FS_TICK)
    ax.grid(True, alpha=0.18, linestyle="--", color="gray")
    ax.set_axisbelow(True)
    sns.despine(ax=ax)
    plt.tight_layout()
    plt.savefig(out_path, dpi=300, bbox_inches="tight")
    plt.close()
    print(f"Saved {out_path}")


# ── Figure 3: Phase breakdown (stacked bar) ───────────────────────────────────

def plot_phase_breakdown(p2s, pos, out_path):
    # P2S phases
    p2s_b1  = np.mean([b['b1_time']  for b in p2s])
    p2s_mt  = np.mean([b['mt_time']  for b in p2s])
    p2s_b2  = np.mean([b['b2_time']  for b in p2s])
    p2s_pht = np.mean([b['pht_time'] for b in p2s])

    # PoS phases
    pos_mem  = np.mean([b['mempool_time']      for b in pos])
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
    ax.legend(fontsize=FS_LEGEND - 2, loc="upper right", ncol=1)
    ax.grid(axis="y", alpha=0.18, linestyle="--", color="gray")
    ax.set_axisbelow(True)
    sns.despine(ax=ax)
    plt.tight_layout()
    plt.savefig(out_path, dpi=300, bbox_inches="tight")
    plt.close()
    print(f"Saved {out_path}")


def main():
    os.makedirs(FIGURES_DIR, exist_ok=True)
    p2s, pos = run_sim()

    plot_cdf(p2s, pos,
             os.path.join(FIGURES_DIR, "latency_cdf.pdf"))
    plot_by_congestion(p2s, pos,
                       os.path.join(FIGURES_DIR, "latency_congestion.pdf"))
    plot_phase_breakdown(p2s, pos,
                         os.path.join(FIGURES_DIR, "latency_breakdown.pdf"))


if __name__ == "__main__":
    main()
