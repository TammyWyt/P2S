#!/usr/bin/env python3
"""Figures: network-environment simulation of P2S vs Ethereum PoS (discrete-event,
GossipSub propagation over a geographic latency matrix). Each panel is one figure.
(a) per-slot latency vs committee size N (95% CI over seeds), P2S vs PoS.
(b) per-slot bandwidth, leader-aggregated O(N) vs naive all-to-all O(N^2).
Reads data/netsim_results.json, writes figures/netsim_latency.pdf and
figures/netsim_bandwidth.pdf."""
import json, os
import matplotlib.pyplot as plt
from matplotlib.ticker import LogLocator
import seaborn as sns

HERE = os.path.dirname(os.path.abspath(__file__))
sns.set_theme(style="ticks")
_DEEP = sns.color_palette("deep")
P2S_C, POS_C = _DEEP[0], _DEEP[3]
LW = 2.8
MS = 9
# Shared font sizes (match across all plot scripts) so panels stay legible
# when scaled down into a tight 2x2 layout.
FS_LABEL  = 24
FS_TICK   = 20
FS_LEGEND = 18


def style_log(ax, x=False, y=False):
    """Force every-decade major ticks plus visible minor ticks so a log axis
    reads unambiguously as log (matplotlib thins ticks under large fonts)."""
    subs = tuple(range(2, 10))
    for on, axis in ((x, ax.xaxis), (y, ax.yaxis)):
        if on:
            axis.set_major_locator(LogLocator(base=10, numticks=20))
            axis.set_minor_locator(LogLocator(base=10, subs=subs, numticks=20))
    ax.tick_params(which="major", length=6)
    ax.tick_params(which="minor", length=3, width=0.8)

d = json.load(open(os.path.join(HERE, "..", "data", "netsim_results.json")))
rows = d["rows"]
N = [r["N"] for r in rows]
pos = [r["pos_lat_s"] * 1000 for r in rows]; pos_ci = [r["pos_ci"] * 1000 for r in rows]
p2s = [r["p2s_lat_s"] * 1000 for r in rows]; p2s_ci = [r["p2s_ci"] * 1000 for r in rows]
bls = [r["agr_mb_bls"] for r in rows]
agg = [r["agr_mb_aggregated"] for r in rows]
naive = [r["agr_mb_naive"] for r in rows]

# Figure (a): per-slot latency vs N
fig, ax = plt.subplots(figsize=(7, 6))
ax.errorbar(N, pos, yerr=pos_ci, color=POS_C, lw=LW, marker="o", ms=MS, capsize=4, label="Ethereum PoS")
ax.errorbar(N, p2s, yerr=p2s_ci, color=P2S_C, lw=LW, marker="s", ms=MS, capsize=4,
            label="P2S")
ax.set_xscale("log")
style_log(ax, x=True)
ax.set_xlabel("Committee size $N$", fontsize=FS_LABEL)
ax.set_ylabel("Per-slot latency (ms)", fontsize=FS_LABEL)
ax.tick_params(labelsize=FS_TICK)
ax.legend(frameon=False, fontsize=FS_LEGEND, loc="upper left")
sns.despine()
fig.tight_layout()
out = os.path.join(HERE, "..", "figures", "netsim_latency.pdf")
fig.savefig(out, bbox_inches="tight")
print("wrote", out)

# Figure (b): per-slot agreement bandwidth vs N
fig, ax = plt.subplots(figsize=(7, 6))
ax.plot(N, naive, color="gray", lw=LW, ls="--", marker="x", ms=MS, label="Naive $O(N^2)$")
ax.plot(N, agg, color=POS_C, lw=LW, ls=":", marker="^", ms=MS, label="Leader $O(NK)$")
ax.plot(N, bls, color=P2S_C, lw=LW, marker="s", ms=MS, label="BLS $O(N)$ (P2S)")
ax.set_xscale("log"); ax.set_yscale("log")
style_log(ax, x=True, y=True)
ax.set_xlabel("Committee size $N$", fontsize=FS_LABEL)
ax.set_ylabel("Agreement bandwidth per slot (MB)", fontsize=FS_LABEL)
ax.tick_params(labelsize=FS_TICK)
ax.legend(frameon=False, fontsize=FS_LEGEND, loc="upper left")
sns.despine()
fig.tight_layout()
out = os.path.join(HERE, "..", "figures", "netsim_bandwidth.pdf")
fig.savefig(out, bbox_inches="tight")
print("wrote", out)
