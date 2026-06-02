#!/usr/bin/env python3
"""Figure: real historical sandwich attacks detected on Ethereum (Uniswap V2+V3,
standard log heuristic) vs what P2S leaves extractable. Each detected attack is
content-dependent, so under P2S its survival probability is 0 (validated on real
EVM by measure_mev). Mirrors BlindPerm (eprint 2023/1061) Fig. 4 in spirit.
Reads real/data/sandwiches.json, writes real/figures/real_sandwiches.pdf."""
import json, os
import matplotlib.pyplot as plt
import seaborn as sns

HERE = os.path.dirname(os.path.abspath(__file__))
sns.set_theme(style="ticks")
_DEEP = sns.color_palette("deep")
P2S_C, POS_C = _DEEP[0], _DEEP[3]
LW = 2.2

d = json.load(open(os.path.join(HERE, "..", "data", "sandwiches.json")))
profits = sorted(d["all_profits_eth"], reverse=True)
n_total = d["n_sandwiches_total"]
total_eth = d["total_extracted_eth"]
median_eth = d["median_per_sandwich_eth"]
blocks = d["blocks_sampled"]

fig, ax = plt.subplots(figsize=(6.6, 4.2))
ranks = list(range(1, len(profits) + 1))
ax.scatter(ranks, profits, color=POS_C, s=42, marker="o", zorder=3,
           label=f"PoS: {len(profits)} real detected sandwiches")
ax.plot(ranks, profits, color=POS_C, lw=LW, alpha=0.6)
# P2S floor at 0 (shown on log axis as a labeled baseline)
ax.axhline(1e-5, color=P2S_C, lw=LW, ls="--",
           label="P2S: extractable = 0 (content-ordering independence)")

ax.set_yscale("log")
ax.set_xlabel("Attack rank (by extracted value)")
ax.set_ylabel("Extracted MEV per sandwich (ETH)")
ax.set_title(f"Real sandwich MEV ({n_total} attacks / {blocks} blocks; "
             f"median {median_eth*1000:.2f} mETH) — P2S eliminates all")
ax.legend(frameon=False, fontsize=8.5, loc="upper right")
sns.despine()
fig.tight_layout()
out = os.path.join(HERE, "..", "figures", "real_sandwiches.pdf")
fig.savefig(out, bbox_inches="tight")
print("wrote", out)
