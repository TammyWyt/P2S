#!/usr/bin/env python3
"""
Measured-MEV figures from real replayed sandwich fixtures.

Emitted as TWO independent single-panel PDFs (each its own figure), sized for
single-column display in a two-column paper (column width ~3.4in):

  mev_measured_validation.pdf — "Replay validation": scatter of independently
      detected on-chain MEV (x) against the faithful EVM-replay PoS MEV (y).
      Points lie on the dashed y=x reference, confirming the replay reproduces
      the on-chain profit.

  mev_measured_elim.pdf — "P2S eliminates it": per-fixture replayed PoS MEV
      (positive) vs P2S MEV (<= 0), fixtures sorted by PoS MEV descending. Every
      sandwich is profitable under PoS but loss-making (extractable MEV = 0)
      under P2S.

Reads real/data/mev_measured_realized.json, writes the two PDFs to figures/, and
copies each into the Overleaf tree.
"""

import json
import os
import shutil

import matplotlib.pyplot as plt
import numpy as np
import seaborn as sns

# Single-column font sizes: legible at ~1:1 display in a two-column paper.
FS_LABEL  = 11
FS_TICK   = 10
FS_LEGEND = 9

FIGSIZE = (3.4, 2.6)

# vlag: index -2 = warm red (Ethereum PoS, more MEV); index 1 = cool blue (P2S)
_VLAG     = sns.color_palette("vlag", n_colors=10)
COLOR_ETH = _VLAG[-2]   # warm red  — Ethereum PoS
COLOR_P2S = _VLAG[1]    # cool blue — P2S

# Repo-relative paths (this file lives in plots/)
REPO_ROOT   = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DATA_PATH   = os.path.join(REPO_ROOT, "real", "data", "mev_measured_realized.json")
FIGURES_DIR = os.path.join(REPO_ROOT, "figures")
OVERLEAF_DIR = "/Users/tammy/Code/P2S_Overleaf/Figures"

VALIDATION_OUT = os.path.join(FIGURES_DIR, "mev_measured_validation.pdf")
ELIM_OUT       = os.path.join(FIGURES_DIR, "mev_measured_elim.pdf")


def load_data(path: str = DATA_PATH) -> dict:
    with open(path, "r") as f:
        return json.load(f)


def plot_validation(data: dict, out_path: str) -> None:
    """Panel (a) as a standalone figure: on-chain detected vs replayed PoS MEV."""
    fixtures = data["per_fixture"]
    onchain = np.array([f["onchain_profit_eth"] for f in fixtures], dtype=float)
    pos     = np.array([f["pos_mev_eth"] for f in fixtures], dtype=float)

    sns.set_theme(style="ticks")
    fig, ax = plt.subplots(figsize=FIGSIZE)
    ax.scatter(onchain, pos, s=26, color=COLOR_ETH, alpha=0.85,
               edgecolor="white", linewidth=0.5, zorder=3, label="Sandwich")
    lo = float(min(onchain.min(), pos.min()))
    hi = float(max(onchain.max(), pos.max()))
    span = hi - lo
    lo -= 0.03 * span
    hi += 0.03 * span
    ax.plot([lo, hi], [lo, hi], ls="--", color="gray", lw=1.4,
            zorder=2, label="$y = x$")
    ax.set_xlim(lo, hi)
    ax.set_ylim(lo, hi)
    ax.set_xlabel("On-chain detected MEV (ETH)", fontsize=FS_LABEL)
    ax.set_ylabel("Replayed PoS MEV (ETH)", fontsize=FS_LABEL)
    ax.tick_params(labelsize=FS_TICK)
    ax.legend(fontsize=FS_LEGEND, loc="upper left", frameon=False)
    sns.despine(ax=ax)

    fig.tight_layout()
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved {out_path}")


def plot_elim(data: dict, out_path: str) -> None:
    """Panel (b) as a standalone figure: PoS MEV vs P2S MEV, sorted descending."""
    fixtures = data["per_fixture"]
    pos = np.array([f["pos_mev_eth"] for f in fixtures], dtype=float)
    p2s = np.array([f["p2s_mev_eth"] for f in fixtures], dtype=float)

    order = np.argsort(-pos)          # PoS MEV descending
    pos_s = pos[order]
    p2s_s = p2s[order]
    idx = np.arange(len(pos_s))

    sns.set_theme(style="ticks")
    fig, ax = plt.subplots(figsize=FIGSIZE)
    ax.axhline(0.0, color="gray", lw=1.2, zorder=1)
    ax.plot(idx, pos_s, color=COLOR_ETH, lw=1.8, marker="o", ms=3.0,
            zorder=3, label="Ethereum PoS")
    ax.plot(idx, p2s_s, color=COLOR_P2S, lw=1.8, marker="o", ms=3.0,
            zorder=3, label="P2S")
    ax.set_xlabel("Sandwich (sorted)", fontsize=FS_LABEL)
    ax.set_ylabel("Extracted MEV (ETH)", fontsize=FS_LABEL)
    ax.tick_params(labelsize=FS_TICK)
    ax.legend(fontsize=FS_LEGEND, loc="upper right", frameon=False)
    sns.despine(ax=ax)

    fig.tight_layout()
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved {out_path}")


def main() -> None:
    data = load_data()
    plot_validation(data, VALIDATION_OUT)
    plot_elim(data, ELIM_OUT)

    os.makedirs(OVERLEAF_DIR, exist_ok=True)
    for src in (VALIDATION_OUT, ELIM_OUT):
        dst = os.path.join(OVERLEAF_DIR, os.path.basename(src))
        shutil.copyfile(src, dst)
        print(f"Copied to {dst}")

    print("\n=== Measured MEV summary ===")
    print(f"  n fixtures:              {data['n']}")
    print(f"  PoS total MEV (ETH):     {data['pos_total_mev_eth']:.6f}")
    print(f"  P2S total MEV (ETH):     {data['p2s_total_mev_eth']:.6f}")
    print(f"  On-chain detected (ETH): {data['onchain_detected_total_eth']:.6f}")
    print(f"  Reduction:               {data['reduction_pct']:.2f}%")


if __name__ == "__main__":
    main()
