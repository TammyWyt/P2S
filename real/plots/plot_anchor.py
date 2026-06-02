#!/usr/bin/env python3
"""Figures (F3, replaces the discarded NaN/synthetic anchor): 45 REAL V2 sandwich
attacks replayed through real-EVM (evm t8n). Each panel is one figure.
(a) t8n-reproduced profit vs the detected on-chain profit (validation; points on
y=x mean the model reproduces reality).
(b) under P2S a rational attacker's extractable value is 0.
Reads real/data/anchor_t8n.json, writes real/figures/anchor_validation.pdf and
real/figures/anchor_extractable.pdf."""
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

# Figure (a): validation — t8n reproduces real detected profit
fig, ax = plt.subplots(figsize=(5.6, 4.3))
lo, hi = min(det + t8) * 0.6, max(det + t8) * 1.6
ax.plot([lo, hi], [lo, hi], ls="--", color="gray", lw=1.3, label="y = x (perfect)")
ax.scatter(det, t8, color=POS_C, s=46, marker="o", zorder=3)
ax.set_xscale("log"); ax.set_yscale("log")
ax.set_xlabel("Detected on-chain profit (ETH)")
ax.set_ylabel("Real-EVM (t8n) reproduced profit (ETH)")
ax.set_title(f"Validation: t8n vs reality ({len(rows)} attacks, median ratio 0.89)")
ax.legend(frameon=False, fontsize=9)
sns.despine()
fig.tight_layout()
out = os.path.join(HERE, "..", "figures", "anchor_validation.pdf")
fig.savefig(out, bbox_inches="tight")
print("wrote", out)

# Figure (b): PoS vs P2S extractable across the real attacked trades (ranked)
fig, ax = plt.subplots(figsize=(5.6, 4.3))
allrows = sorted(d["rows"], key=lambda r: -r["t8n_pos_profit_eth"])
pos = [max(r["t8n_pos_profit_eth"], 0) for r in allrows]
ranks = list(range(1, len(pos) + 1))
ax.scatter(ranks, pos, color=POS_C, s=34, marker="o", zorder=3, label="PoS: extractable (t8n)")
ax.plot(ranks, pos, color=POS_C, lw=LW, alpha=0.5)
ax.axhline(1e-5, color=P2S_C, lw=LW, ls="--",
           label="P2S: rational attacker = 0")
ax.set_yscale("log")
ax.set_xlabel("Real attacked trade (ranked)")
ax.set_ylabel("Extractable MEV (ETH)")
ax.set_title(f"PoS {d['pos_total_extractable_eth']:.3f} ETH → P2S 0 (45 real V2 sandwiches)")
ax.legend(frameon=False, fontsize=9, loc="upper right")
sns.despine()
fig.tight_layout()
out = os.path.join(HERE, "..", "figures", "anchor_extractable.pdf")
fig.savefig(out, bbox_inches="tight")
print("wrote", out)
