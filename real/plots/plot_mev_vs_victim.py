#!/usr/bin/env python3
"""Figure: measured sandwich MEV vs victim size, PoS vs P2S, on real pool
reserves (real EVM execution via evm t8n). Replaces the old simulated MEV figure.
Reads data/mev_sweep.json, writes figures/mev_vs_victim.pdf."""
import json, os
import matplotlib.pyplot as plt
import seaborn as sns

HERE = os.path.dirname(os.path.abspath(__file__))
sns.set_theme(style="ticks")
_DEEP = sns.color_palette("deep")
P2S_C, POS_C = _DEEP[0], _DEEP[3]   # blue = P2S, red-orange = PoS
LW = 2.2

data = json.load(open(os.path.join(HERE, "..", "data", "mev_sweep.json")))
pools = data["pools"]

fig, ax = plt.subplots(figsize=(6.4, 4.2))
styles = ["-", "--", ":"]
for (name, p), ls in zip(pools.items(), styles):
    xs = [c["victim_eth"] for c in p["curve"]]
    pos = [c["pos_ext_eth"] for c in p["curve"]]
    ax.plot(xs, pos, ls=ls, color=POS_C, lw=LW, marker="o", ms=5,
            label=f"PoS — {name} ({p['reserve_eth']:.0f} ETH pool)")

# P2S is identically zero across all pools and sizes; one flat line conveys it.
any_pool = next(iter(pools.values()))
xs = [c["victim_eth"] for c in any_pool["curve"]]
ax.plot(xs, [0]*len(xs), color=P2S_C, lw=LW, marker="s", ms=5, label="P2S — all pools")

ax.set_xscale("log")
ax.set_xlabel("Victim swap size (ETH)")
ax.set_ylabel("Extractable sandwich MEV (ETH)")
ax.set_title("Measured sandwich MEV on real V2 reserves (1% victim slippage)")
ax.legend(frameon=False, fontsize=8, loc="upper left")
sns.despine()
fig.tight_layout()
out = os.path.join(HERE, "..", "figures", "mev_vs_victim.pdf")
fig.savefig(out, bbox_inches="tight")
print("wrote", out)
