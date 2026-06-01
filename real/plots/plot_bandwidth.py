#!/usr/bin/env python3
"""Figure: P2S per-slot bandwidth overhead vs proposer count N, for several block
sizes K. The per-tx overhead (PHT commitment) is a flat floor; the set-union
agreement adds O(N*K) and dominates at large N. Reads real/data/bandwidth.json,
writes real/figures/bandwidth_overhead.pdf."""
import json, os
import matplotlib.pyplot as plt
import seaborn as sns

HERE = os.path.dirname(os.path.abspath(__file__))
sns.set_theme(style="ticks")
_DEEP = sns.color_palette("deep")
LW = 2.2

d = json.load(open(os.path.join(HERE, "..", "data", "bandwidth.json")))
rows = d["Rows"]
Ks = sorted({r["K"] for r in rows})
Ns = sorted({r["N"] for r in rows})

fig, ax = plt.subplots(figsize=(6.4, 4.2))
# one line per block size K; color by the deep palette
for i, K in enumerate([k for k in (100, 500, 1000) if k in Ks]):
    ys = [next(r["TotalB"] for r in rows if r["K"] == K and r["N"] == N) / 1024 for N in Ns]
    ax.plot(Ns, ys, marker="o", lw=LW, color=_DEEP[i % len(_DEEP)],
            label=f"K = {K} txs/slot")

ax.set_xlabel("Proposer count $N$")
ax.set_ylabel("Per-slot bandwidth overhead (KB)")
ax.set_title("P2S bandwidth overhead (PHT commitments + set-union agreement)")
ax.legend(frameon=False, fontsize=9)
sns.despine()
fig.tight_layout()
out = os.path.join(HERE, "..", "figures", "bandwidth_overhead.pdf")
fig.savefig(out, bbox_inches="tight")
print("wrote", out)
