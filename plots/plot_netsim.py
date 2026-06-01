#!/usr/bin/env python3
"""Figure: network-environment simulation of P2S vs Ethereum PoS (discrete-event,
GossipSub propagation over a geographic latency matrix). Left: per-slot latency
vs committee size N (95% CI over seeds), P2S vs PoS, against the 12 s slot budget.
Right: per-slot bandwidth, leader-aggregated O(N) vs naive all-to-all O(N^2).
Reads data/netsim_results.json, writes figures/netsim.pdf."""
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
agg_mb = [r["p2s_mb_per_slot"] for r in rows]; naive_mb = [r["naive_mb_per_slot"] for r in rows]

fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4.3))

ax1.errorbar(N, pos, yerr=pos_ci, color=POS_C, lw=LW, marker="o", capsize=3, label="Ethereum PoS")
ax1.errorbar(N, p2s, yerr=p2s_ci, color=P2S_C, lw=LW, marker="s", capsize=3, label="P2S (B1+reveal+agree+B2)")
ax1.set_xscale("log")
ax1.set_xlabel("Committee size $N$"); ax1.set_ylabel("Per-slot latency (ms)")
ax1.set_title(f"Network latency vs N (K={d['K']} tx, {d['seeds']} seeds, 95% CI)")
ax1.legend(frameon=False, fontsize=9, loc="upper left")

ax2.plot(N, naive_mb, color="gray", lw=LW, ls="--", marker="x", label="naive all-to-all  $O(N^2)$")
ax2.plot(N, agg_mb, color=P2S_C, lw=LW, marker="s", label="leader-aggregated  $O(N)$")
ax2.set_xscale("log"); ax2.set_yscale("log")
ax2.set_xlabel("Committee size $N$"); ax2.set_ylabel("P2S bandwidth per slot (MB)")
ax2.set_title("Set-union agreement: aggregation makes it feasible")
ax2.legend(frameon=False, fontsize=9, loc="upper left")

sns.despine()
fig.tight_layout()
out = os.path.join(HERE, "..", "figures", "netsim.pdf")
fig.savefig(out, bbox_inches="tight")
print("wrote", out)
