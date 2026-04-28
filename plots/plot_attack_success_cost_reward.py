#!/usr/bin/env python3
"""
Design evaluation figures: two separate plots evaluating P2S.

  cumulative_mev.pdf
      Cumulative MEV extraction over 1,000 blocks — Ethereum PoS vs P2S.

  cost_gain_comparison.pdf
      Per-block cost vs gain scatter for each attack strategy.
      Each point = one simulated block. Hue = strategy, size = congestion level.
      Per-block data from block_ledger (ETH: front_run/sandwich/arbitrage;
      P2S: blind_insert). P2S-only agents (inference, b2_proposer, cross_blk_arb)
      shown as aggregate means from the 1,000-block simulation.

Data sources:
  - data/p2s_mev_attacks.json    (cumulative series + P2S agent means)
  - data/block_ledger_*.json     (per-block per-strategy outcomes)

Output: figures/cumulative_mev.pdf, figures/cost_gain_comparison.pdf
"""

import glob
import json
import os
import sys

import matplotlib.pyplot as plt
import numpy as np
import seaborn as sns

DATA_DIR    = "data"
FIGURES_DIR = "figures"

# Diverging vlag palette: index 1 = cool blue, index -2 = warm red.
# ETH = warm (more MEV); P2S = cool (less MEV) — consistent with scatter colors.
_VLAG     = sns.color_palette("vlag", n_colors=10)
COLOR_ETH = _VLAG[-2]   # warm red  — Ethereum PoS
COLOR_P2S = _VLAG[1]    # cool blue — P2S

# Shared font sizes (match across all plot scripts)
FS_LABEL  = 24
FS_TICK   = 20
FS_LEGEND = 18

STRATEGY_LABELS = {
    "front_run":        "Front-Run (PoS)",
    "sandwich":         "Sandwich (PoS)",
    "arbitrage":        "Arbitrage (PoS)",
    "blind_insert_p2s": "Blind Insert (P2S)",
    "cross_blk_arb":    "Arbitrage (P2S)",
}

# Not real P2S attacks: inference is not applicable; b2_proposer is invalid
# because the P2S mechanism prevents B2 transaction reordering.
_SKIP_P2S_AGENTS = {"inference", "b2_proposer"}

# Warm tones for PoS strategies (flare palette), cool tones for P2S (mako palette)
_FLARE = sns.color_palette("flare", n_colors=8)
_MAKO  = sns.color_palette("mako",  n_colors=8)
STRATEGY_COLORS = {
    "Front-Run (PoS)":    _FLARE[7],  # deep red
    "Sandwich (PoS)":     _FLARE[5],  # salmon/pink
    "Arbitrage (PoS)":    _FLARE[3],  # amber/orange
    "Blind Insert (P2S)": _MAKO[5],   # blue
    "Arbitrage (P2S)":    _MAKO[3],   # teal-green
}


# ─────────────────────────────────────────────────────────────────────────────
# Data loaders
# ─────────────────────────────────────────────────────────────────────────────

def _load_mev_series(data_dir: str):
    """Return (pos_series, p2s_series, p2s_agents_dict) from p2s_mev_attacks.json."""
    path = os.path.join(data_dir, "p2s_mev_attacks.json")
    if not os.path.isfile(path):
        return None, None, {}
    with open(path) as f:
        d = json.load(f)
    pos        = d.get("baseline_pos_mev", [])
    p2s        = d.get("baseline_p2s_mev", [])
    p2s_agents = d.get("baseline", {}).get("p2s_summary", {}).get("strategies", {})
    return pos, p2s, p2s_agents


def _load_block_ledger(data_dir: str):
    files = glob.glob(os.path.join(data_dir, "block_ledger_*.json"))
    if not files:
        return None
    path = max(files, key=os.path.getmtime)
    with open(path) as f:
        return json.load(f)


# ─────────────────────────────────────────────────────────────────────────────
# Panel: Cumulative MEV extraction
# ─────────────────────────────────────────────────────────────────────────────

def _panel_cumulative(ax, pos_series, p2s_series):
    n       = min(len(pos_series), len(p2s_series))
    # Prepend origin so the curve starts at (0, 0)
    blocks  = np.arange(0, n + 1)
    cum_pos = np.concatenate([[0], np.cumsum(pos_series[:n])])
    cum_p2s = np.concatenate([[0], np.cumsum(p2s_series[:n])])

    ax.plot(blocks, cum_pos, color=COLOR_ETH, lw=2.0, label="Ethereum PoS")
    ax.plot(blocks, cum_p2s, color=COLOR_P2S, lw=2.0, label="P2S")
    ax.fill_between(blocks, cum_p2s, cum_pos, alpha=0.12, color=COLOR_P2S)

    ax.set_xlim(0, n)
    ax.set_ylim(0)
    ax.set_xlabel("Block", fontsize=FS_LABEL, fontweight="bold")
    ax.set_ylabel("Cumulative MEV extracted (ETH)", fontsize=FS_LABEL, fontweight="bold")
    ax.tick_params(labelsize=FS_TICK)
    ax.legend(fontsize=FS_LEGEND, loc="upper left")
    sns.despine(ax=ax)
    ax.grid(True, alpha=0.2, linestyle="--", color="gray")
    ax.set_axisbelow(True)


# ─────────────────────────────────────────────────────────────────────────────
# Panel: Cost vs Gain scatter per attack strategy
# ─────────────────────────────────────────────────────────────────────────────

def _panel_cost_gain(ax, block_ledger, p2s_agents):
    import pandas as pd

    Y_CLIP = 0.20   # ETH — clips 6 extreme outliers (<2% of successes)

    records = []
    if block_ledger:
        for b in block_ledger.get("blocks", []):
            for strat, v in b["ethereum_pos"]["attack"].get("all_strategies", {}).items():
                if v["success"]:
                    records.append({
                        "Strategy": STRATEGY_LABELS.get(strat, strat),
                        "cost":     v["cost_eth"],
                        "gain":     v["gain_eth"],
                        "clipped":  v["gain_eth"] > Y_CLIP,
                    })
            atk = b["p2s"]["attack"]
            if atk["success"]:
                records.append({
                    "Strategy": STRATEGY_LABELS.get(atk["strategy"], atk["strategy"]),
                    "cost":     atk["cost_eth"],
                    "gain":     atk["gain_eth"],
                    "clipped":  atk["gain_eth"] > Y_CLIP,
                })

    df = pd.DataFrame(records)
    df["gain_plot"] = df["gain"].clip(upper=Y_CLIP)

    # Main scatter — successful attacks at actual coordinates
    sns.scatterplot(
        data=df[~df["clipped"]],
        x="cost", y="gain_plot",
        hue="Strategy",
        palette=STRATEGY_COLORS,
        alpha=0.65, s=60,
        ax=ax,
    )
    # Clipped outliers — same color, triangle marker at y=Y_CLIP
    for strat, grp in df[df["clipped"]].groupby("Strategy"):
        ax.scatter(grp["cost"], [Y_CLIP] * len(grp),
                   color=STRATEGY_COLORS.get(strat, "#555"),
                   marker="^", s=80, alpha=0.8, zorder=6)

    # Break-even line: gain = cost (above = profitable, below = loss even when successful)
    xlim = ax.get_xlim()
    xs = np.linspace(0, Y_CLIP, 200)
    ax.plot(xs, xs, color="gray", lw=1.2, ls="--", alpha=0.6, zorder=1)
    ax.fill_between(xs, xs, Y_CLIP, alpha=0.04, color="#2CA02C")
    ax.text(Y_CLIP * 0.68, Y_CLIP * 0.90, "Profitable\n(gain > cost)",
            fontsize=FS_LEGEND - 2, color="gray", alpha=0.7, va="top")

    ax.set_xlim(0)
    ax.set_ylim(0, Y_CLIP * 1.05)
    ax.set_xlabel("Cost per attack (ETH)", fontsize=FS_LABEL, fontweight="bold")
    ax.set_ylabel("Gain per attack (ETH)", fontsize=FS_LABEL, fontweight="bold")
    ax.tick_params(labelsize=FS_TICK)
    ax.legend(fontsize=FS_LEGEND, loc="upper right")
    sns.despine(ax=ax)


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    repo_root   = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    data_dir    = os.path.join(repo_root, DATA_DIR)
    figures_dir = os.path.join(repo_root, FIGURES_DIR)

    pos_series, p2s_series, p2s_agents = _load_mev_series(data_dir)
    block_ledger = _load_block_ledger(data_dir)

    if pos_series is None:
        print("Missing p2s_mev_attacks.json. Run simulation scripts first.", file=sys.stderr)
        sys.exit(1)
    if block_ledger is None:
        print("No block_ledger_*.json found — cost/gain scatter will use only aggregate means.",
              file=sys.stderr)

    os.makedirs(figures_dir, exist_ok=True)
    sns.set_theme(style="ticks")

    # Figure (a): Cumulative MEV
    fig, ax = plt.subplots(figsize=(8, 5))
    _panel_cumulative(ax, pos_series, p2s_series)
    plt.tight_layout()
    out_a = os.path.join(figures_dir, "cumulative_mev.pdf")
    plt.savefig(out_a, dpi=300, bbox_inches="tight")
    plt.close()
    print(f"Saved {out_a}")

    # Figure (b): Cost vs Gain comparison
    fig, ax = plt.subplots(figsize=(10, 6))
    _panel_cost_gain(ax, block_ledger, p2s_agents)
    plt.tight_layout()
    out_b = os.path.join(figures_dir, "cost_gain_comparison.pdf")
    plt.savefig(out_b, dpi=300, bbox_inches="tight")
    plt.close()
    print(f"Saved {out_b}")


if __name__ == "__main__":
    main()
