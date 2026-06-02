#!/usr/bin/env python3
"""Figures: network-sim robustness sweeps. Each panel is one figure.
(a) per-slot latency vs block size K (N=500).
(b) per-slot latency vs GossipSub fanout D (N=500, K=150).
Shows the P2S-vs-PoS gap is stable across operating points, not a single-point
artifact. Reads data/netsim_sweeps.json, writes figures/netsim_sweep_blocksize.pdf
and figures/netsim_sweep_fanout.pdf."""
import json, os
import matplotlib.pyplot as plt
import seaborn as sns

HERE = os.path.dirname(os.path.abspath(__file__))
sns.set_theme(style="ticks")
_DEEP = sns.color_palette("deep")
P2S_C, POS_C = _DEEP[0], _DEEP[3]
LW = 2.2

d = json.load(open(os.path.join(HERE, "..", "data", "netsim_sweeps.json")))
ks = d["K_sweep"]; fs = d["fanout_sweep"]

# Figure (a): latency vs block size K
fig, ax = plt.subplots(figsize=(6, 4.3))
K = [r["K"] for r in ks]
ax.plot(K, [r["pos_lat_s"] * 1000 for r in ks], color=POS_C, lw=LW, marker="o", label="Ethereum PoS")
ax.plot(K, [r["p2s_lat_s"] * 1000 for r in ks], color=P2S_C, lw=LW, marker="s", label="P2S")
ax.set_xlabel("Block size $K$ (txs/slot)"); ax.set_ylabel("Per-slot latency (ms)")
ax.set_title(f"Latency vs block size (N={d['K_sweep_N']})")
ax.legend(frameon=False, fontsize=9, loc="upper left")
sns.despine()
fig.tight_layout()
out = os.path.join(HERE, "..", "figures", "netsim_sweep_blocksize.pdf")
fig.savefig(out, bbox_inches="tight")
print("wrote", out)

# Figure (b): latency vs GossipSub fanout D
fig, ax = plt.subplots(figsize=(6, 4.3))
D = [r["fanout"] for r in fs]
ax.plot(D, [r["pos_lat_s"] * 1000 for r in fs], color=POS_C, lw=LW, marker="o", label="Ethereum PoS")
ax.plot(D, [r["p2s_lat_s"] * 1000 for r in fs], color=P2S_C, lw=LW, marker="s", label="P2S")
ax.set_xlabel("GossipSub fanout $D$"); ax.set_ylabel("Per-slot latency (ms)")
ax.set_title(f"Latency vs fanout (N={d['fanout_sweep_N']}, K=150)")
ax.legend(frameon=False, fontsize=9, loc="upper right")
sns.despine()
fig.tight_layout()
out = os.path.join(HERE, "..", "figures", "netsim_sweep_fanout.pdf")
fig.savefig(out, bbox_inches="tight")
print("wrote", out)
