#!/usr/bin/env python3
"""
Honest-user welfare comparison: P2S vs Ethereum PoS.

Loads data/block_ledger_1000.json and produces two subplots:

  welfare_comparison.pdf
    Top:    Violin plots of per-block victim welfare loss (ETH) — P2S vs PoS
    Bottom: CDF of per-block user aggregate net loss — P2S vs PoS

Saved to figures/.
"""

import json
import os
import sys

import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import numpy as np
import seaborn as sns

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DATA_PATH    = os.path.join(_REPO, "data", "block_ledger_1000.json")
FIGURES_DIR  = os.path.join(_REPO, "figures")

FS_LABEL  = 24
FS_TICK   = 20
FS_LEGEND = 18
FS_ANNOT  = 15

_DEEP = sns.color_palette("deep")
C_P2S = _DEEP[0]   # steel blue
C_POS = _DEEP[3]   # red-orange


def load_data():
    with open(DATA_PATH) as f:
        d = json.load(f)
    blocks = d["blocks"]

    p2s_welfare = np.array([b["p2s"]["block_state"]["victim_welfare_loss_eth"] for b in blocks])
    pos_welfare = np.array([b["ethereum_pos"]["block_state"]["victim_welfare_loss_eth"] for b in blocks])

    p2s_user = np.array([b["p2s"]["wallet_deltas"]["users_aggregate_net_eth"] for b in blocks])
    pos_user = np.array([b["ethereum_pos"]["wallet_deltas"]["users_aggregate_net_eth"] for b in blocks])

    p2s_slip = np.array([b["p2s"]["attack"]["victim_slippage_eth"] for b in blocks])
    pos_slip = np.array([b["ethereum_pos"]["attack"]["victim_slippage_eth"] for b in blocks])

    return p2s_welfare, pos_welfare, p2s_user, pos_user, p2s_slip, pos_slip


def main():
    os.makedirs(FIGURES_DIR, exist_ok=True)
    p2s_welfare, pos_welfare, p2s_user, pos_user, p2s_slip, pos_slip = load_data()

    sns.set_theme(style="ticks")

    # ── CDF of per-block victim welfare loss ──────────────────────────────────
    fig, ax = plt.subplots(figsize=(7, 6))
    for vals, label, col in [(pos_welfare, "Ethereum PoS", C_POS),
                              (p2s_welfare, "P2S",          C_P2S)]:
        sorted_v = np.sort(vals)
        cdf      = np.arange(1, len(sorted_v) + 1) / len(sorted_v)
        ax.plot(sorted_v, cdf, color=col, lw=2.2, label=label)

    ax.set_xlabel("Victim welfare loss / block (ETH)", fontsize=FS_LABEL, fontweight="bold")
    ax.set_ylabel("CDF", fontsize=FS_LABEL, fontweight="bold")
    ax.tick_params(labelsize=FS_TICK)
    ax.set_ylim(bottom=0)
    ax.legend(fontsize=FS_LEGEND, loc="lower right", frameon=False)
    ax.grid(True, alpha=0.18, linestyle="--", color="gray")
    ax.set_axisbelow(True)
    sns.despine(ax=ax)

    plt.tight_layout()
    out2 = os.path.join(FIGURES_DIR, "welfare_cdf.pdf")

    plt.savefig(out2, dpi=300, bbox_inches="tight")
    plt.close()
    print(f"Saved {out2}")

    # ── summary stats ─────────────────────────────────────────────────────────
    reduction = (1 - p2s_welfare.mean() / pos_welfare.mean()) * 100
    print(f"\nVictim welfare loss (ETH/block):")
    print(f"  PoS mean:  {pos_welfare.mean():.4f}  median: {np.median(pos_welfare):.4f}")
    print(f"  P2S mean:  {p2s_welfare.mean():.4f}  median: {np.median(p2s_welfare):.4f}")
    print(f"  Reduction: {reduction:.1f}%")
    print(f"\nUser aggregate net (ETH/block):")
    print(f"  PoS mean:  {pos_user.mean():.4f}")
    print(f"  P2S mean:  {p2s_user.mean():.4f}")
    pct_better = (p2s_user > pos_user).mean() * 100
    print(f"  Blocks where P2S users better off: {pct_better:.1f}%")


if __name__ == "__main__":
    main()
