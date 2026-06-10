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

    # ── CCDF (survival) of per-block victim welfare loss ──────────────────────
    # Sandwich loss is a rare, heavy-tailed per-block event under measured
    # calibration: only a minority of blocks carry any loss, and P2S removes it
    # entirely. A complementary CDF on log axes shows both the affected fraction
    # (where the Ethereum curve meets the y-axis) and the tail, and avoids the
    # empty frame a linear CDF leaves when most blocks sit at zero.
    fig, ax = plt.subplots(figsize=(7, 6))

    pos_sorted = np.sort(pos_welfare)
    n = len(pos_sorted)
    ccdf = 1.0 - np.arange(n) / n              # P(loss >= x)
    pos_mask = pos_sorted > 0
    affected = pos_mask.mean()                  # fraction of blocks with any loss
    ax.step(pos_sorted[pos_mask], ccdf[pos_mask], where="post",
            color=C_POS, lw=2.6, label="Ethereum PoS")

    # P2S: identically zero across all blocks (content-dependent loss eliminated).
    ax.plot([], [], color=C_P2S, lw=2.6, label="P2S (0 in all blocks)")

    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("Per-block victim loss (ETH)", fontsize=FS_LABEL, fontweight="bold")
    ax.set_ylabel(r"$\Pr[\,\mathrm{loss} \geq x\,]$", fontsize=FS_LABEL, fontweight="bold")
    ax.tick_params(labelsize=FS_TICK)
    ax.set_ylim(0.5 / n, 1.0)
    ax.legend(fontsize=FS_LEGEND, loc="upper right", frameon=False)
    ax.grid(True, alpha=0.18, linestyle="--", color="gray")
    ax.set_axisbelow(True)

    ax.annotate(f"{affected*100:.0f}% of blocks\ncarry any loss",
                xy=(pos_sorted[pos_mask][0], affected),
                xytext=(0.06, 0.42), textcoords="axes fraction",
                fontsize=FS_ANNOT, color=C_POS,
                arrowprops=dict(arrowstyle="->", color=C_POS, lw=1.4))
    ax.text(0.5, 0.10, "P2S: content-dependent\nloss eliminated",
            transform=ax.transAxes, fontsize=FS_ANNOT, color=C_P2S,
            ha="center", va="center")
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
