#!/usr/bin/env python3
"""Figure: P2S per-phase network latency vs proposer count N (real TCP mesh,
50 ms injected one-way link delay). The B1/B2 broadcast stays ~one link-delay
regardless of N (parallel fan-out); the all-to-all set-union agreement holds at
~1 RTT for small committees but its O(N^2) message volume inflates latency at
large N. Reads real/data/latency.json, writes real/figures/latency_vs_n.pdf."""
import json, os
import matplotlib.pyplot as plt
import seaborn as sns

HERE = os.path.dirname(os.path.abspath(__file__))
sns.set_theme(style="ticks")
_DEEP = sns.color_palette("deep")
LW = 2.2

d = json.load(open(os.path.join(HERE, "..", "data", "latency.json")))
rows = d["Rows"]
Ns = [r["N"] for r in rows]
bcast = [r["BroadcastMs"] for r in rows]
agree = [r["AgreementMs"] for r in rows]

fig, ax = plt.subplots(figsize=(6.4, 4.2))
ax.plot(Ns, bcast, marker="o", lw=LW, color=_DEEP[0], label="B1/B2 broadcast (leader $\\to$ all)")
ax.plot(Ns, agree, marker="s", lw=LW, color=_DEEP[3], label="set-union agreement (all-to-all)")
ax.axhline(d["LinkDelayMs"], ls=":", color="gray", lw=1.3, label=f'one-way link delay ({d["LinkDelayMs"]:.0f} ms)')

ax.set_xlabel("Proposer count $N$")
ax.set_ylabel("Phase latency (ms)")
ax.set_title(f"P2S network-round latency (real TCP mesh, K={d['K']} refs/msg)")
ax.legend(frameon=False, fontsize=9, loc="upper left")
sns.despine()
fig.tight_layout()
out = os.path.join(HERE, "..", "figures", "latency_vs_n.pdf")
fig.savefig(out, bbox_inches="tight")
print("wrote", out)
