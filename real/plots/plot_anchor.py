#!/usr/bin/env python3
"""Figure (F3, replaces the discarded NaN/synthetic anchor): 45 REAL V2 sandwich
attacks replayed through real-EVM (evm t8n). Left: t8n-reproduced profit vs the
detected on-chain profit (validation; points on y=x mean the model reproduces
reality). Right/overlay: under P2S a rational attacker's extractable value is 0.
Reads real/data/anchor_t8n.json, writes real/figures/anchor_validation.pdf."""
import json, os
import matplotlib.pyplot as plt
import seaborn as sns

HERE = os.path.dirname(os.path.abspath(__file__))
sns.set_theme(style="ticks")
_DEEP = sns.color_palette("deep")
P2S_C, POS_C = _DEEP[0], _DEEP[3]
LW = 2.2

d = json.load(open(os.path.join(HERE, "..", "data", "anchor_t8n.json")))
rows = [r for r in d["rows"] if r["detected_profit_eth"] > 1e-4 and r["t8n_pos_profit_eth"] > 1e-4]
det = [r["detected_profit_eth"] for r in rows]
t8 = [r["t8n_pos_profit_eth"] for r in rows]

fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10.4, 4.3))

# Left: validation — t8n reproduces real detected profit
lo, hi = min(det + t8) * 0.6, max(det + t8) * 1.6
ax1.plot([lo, hi], [lo, hi], ls="--", color="gray", lw=1.3, label="y = x (perfect)")
ax1.scatter(det, t8, color=POS_C, s=46, zorder=3)
ax1.set_xscale("log"); ax1.set_yscale("log")
ax1.set_xlabel("Detected on-chain profit (ETH)")
ax1.set_ylabel("Real-EVM (t8n) reproduced profit (ETH)")
ax1.set_title(f"Validation: t8n vs reality ({len(rows)} attacks, median ratio 0.89)")
ax1.legend(frameon=False, fontsize=9)

# Right: PoS vs P2S extractable across the real attacked trades (ranked)
allrows = sorted(d["rows"], key=lambda r: -r["t8n_pos_profit_eth"])
pos = [max(r["t8n_pos_profit_eth"], 0) for r in allrows]
ranks = list(range(1, len(pos) + 1))
ax2.scatter(ranks, pos, color=POS_C, s=34, zorder=3, label="PoS: extractable (t8n)")
ax2.plot(ranks, pos, color=POS_C, lw=LW, alpha=0.5)
ax2.axhline(1e-5, color=P2S_C, lw=LW, ls="--",
            label="P2S: rational attacker = 0")
ax2.set_yscale("log")
ax2.set_xlabel("Real attacked trade (ranked)")
ax2.set_ylabel("Extractable MEV (ETH)")
ax2.set_title(f"PoS {d['pos_total_extractable_eth']:.3f} ETH → P2S 0 (45 real V2 sandwiches)")
ax2.legend(frameon=False, fontsize=9, loc="upper right")

sns.despine()
fig.tight_layout()
out = os.path.join(HERE, "..", "figures", "anchor_validation.pdf")
fig.savefig(out, bbox_inches="tight")
print("wrote", out)
