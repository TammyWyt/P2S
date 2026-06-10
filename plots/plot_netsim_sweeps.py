#!/usr/bin/env python3
"""Figures: network-sim robustness sweeps. Each panel is one figure.
(a) per-slot latency vs block size K (N=500).
(b) per-slot latency vs gossip peers D (N=500, K=150).
Shows the P2S-vs-PoS gap is stable across operating points, not a single-point
artifact. Reads data/netsim_sweeps.json, writes figures/netsim_sweep_blocksize.pdf
and figures/netsim_sweep_peers.pdf."""
import json, os
import matplotlib.pyplot as plt
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

d = json.load(open(os.path.join(HERE, "..", "data", "netsim_sweeps.json")))
ks = d["K_sweep"]; fs = d["fanout_sweep"]

# Figure (a): latency vs block size K
fig, ax = plt.subplots(figsize=(7, 6))
K = [r["K"] for r in ks]
ax.errorbar(K, [r["pos_lat_s"] * 1000 for r in ks], yerr=[r.get("pos_ci", 0) * 1000 for r in ks],
            color=POS_C, lw=LW, marker="o", ms=MS, capsize=4, label="Ethereum PoS")
ax.errorbar(K, [r["p2s_lat_s"] * 1000 for r in ks], yerr=[r.get("p2s_ci", 0) * 1000 for r in ks],
            color=P2S_C, lw=LW, marker="s", ms=MS, capsize=4, label="P2S")
ax.set_xlabel("Block size $K$ (txs/slot)", fontsize=FS_LABEL, fontweight="bold")
ax.set_ylabel("Per-slot latency (ms)", fontsize=FS_LABEL, fontweight="bold")
ax.tick_params(labelsize=FS_TICK)
ax.legend(frameon=False, fontsize=FS_LEGEND, loc="upper left")
sns.despine()
fig.tight_layout()
out = os.path.join(HERE, "..", "figures", "netsim_sweep_blocksize.pdf")
fig.savefig(out, bbox_inches="tight")
print("wrote", out)

# Figure (b): latency vs GossipSub fanout D
fig, ax = plt.subplots(figsize=(7, 6))
D = [r["fanout"] for r in fs]
ax.errorbar(D, [r["pos_lat_s"] * 1000 for r in fs], yerr=[r.get("pos_ci", 0) * 1000 for r in fs],
            color=POS_C, lw=LW, marker="o", ms=MS, capsize=4, label="Ethereum PoS")
ax.errorbar(D, [r["p2s_lat_s"] * 1000 for r in fs], yerr=[r.get("p2s_ci", 0) * 1000 for r in fs],
            color=P2S_C, lw=LW, marker="s", ms=MS, capsize=4, label="P2S")
ax.set_xlabel("Gossip peers $D$", fontsize=FS_LABEL, fontweight="bold")
ax.set_ylabel("Per-slot latency (ms)", fontsize=FS_LABEL, fontweight="bold")
ax.tick_params(labelsize=FS_TICK)
ax.legend(frameon=False, fontsize=FS_LEGEND, loc="upper right")
sns.despine()
fig.tight_layout()
out = os.path.join(HERE, "..", "figures", "netsim_sweep_peers.pdf")
fig.savefig(out, bbox_inches="tight")
print("wrote", out)
