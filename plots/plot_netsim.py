#!/usr/bin/env python3
"""Figures: network-environment simulation of P2S vs Ethereum PoS (discrete-event,
GossipSub propagation over a geographic latency matrix). Each panel is one figure.
(a) per-slot latency vs committee size N (95% CI over seeds), P2S vs PoS.
(b) per-slot bandwidth, leader-aggregated O(N) vs naive all-to-all O(N^2).
Reads data/netsim_results.json, writes figures/netsim_latency.pdf and
figures/netsim_bandwidth.pdf."""
import json, os
import matplotlib.pyplot as plt
import seaborn as sns

HERE = os.path.dirname(os.path.abspath(__file__))
sns.set_theme(style="ticks")
_DEEP = sns.color_palette("deep")
P2S_C, POS_C = _DEEP[0], _DEEP[3]
LW = 2.2

d = json.load(open(os.path.join(HERE, "..", "data", "netsim_results.json")))
rows = d["rows"]
N = [r["N"] for r in rows]
pos = [r["pos_lat_s"] * 1000 for r in rows]; pos_ci = [r["pos_ci"] * 1000 for r in rows]
p2s = [r["p2s_lat_s"] * 1000 for r in rows]; p2s_ci = [r["p2s_ci"] * 1000 for r in rows]
bls = [r["agr_mb_bls"] for r in rows]
agg = [r["agr_mb_aggregated"] for r in rows]
naive = [r["agr_mb_naive"] for r in rows]

# Figure (a): per-slot latency vs N
fig, ax = plt.subplots(figsize=(6, 4.3))
ax.errorbar(N, pos, yerr=pos_ci, color=POS_C, lw=LW, marker="o", capsize=3, label="Ethereum PoS")
ax.errorbar(N, p2s, yerr=p2s_ci, color=P2S_C, lw=LW, marker="s", capsize=3,
            label="P2S (B1 + reveal + BLS agree + B2)")
ax.set_xscale("log")
ax.set_xlabel("Committee size $N$"); ax.set_ylabel("Per-slot latency (ms)")
ax.set_title(f"Network latency vs N (K={d['K']} tx, {d['seeds']} seeds, 95% CI)")
ax.legend(frameon=False, fontsize=9, loc="upper left")
sns.despine()
fig.tight_layout()
out = os.path.join(HERE, "..", "figures", "netsim_latency.pdf")
fig.savefig(out, bbox_inches="tight")
print("wrote", out)

# Figure (b): per-slot agreement bandwidth vs N
fig, ax = plt.subplots(figsize=(6, 4.3))
ax.plot(N, naive, color="gray", lw=LW, ls="--", marker="x", label="naive all-to-all  $O(N^2)$")
ax.plot(N, agg, color=POS_C, lw=LW, ls=":", marker="^", label="leader full-set  $O(NK)$")
ax.plot(N, bls, color=P2S_C, lw=LW, marker="s", label="BLS digest vote  $O(N)$ (P2S)")
ax.set_xscale("log"); ax.set_yscale("log")
ax.set_xlabel("Committee size $N$"); ax.set_ylabel("Agreement bandwidth per slot (MB)")
ax.set_title("Set-union agreement design: BLS vote is negligible")
ax.legend(frameon=False, fontsize=9, loc="upper left")
sns.despine()
fig.tight_layout()
out = os.path.join(HERE, "..", "figures", "netsim_bandwidth.pdf")
fig.savefig(out, bbox_inches="tight")
print("wrote", out)
