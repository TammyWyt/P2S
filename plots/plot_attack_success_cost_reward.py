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
FS_LABEL  = 30
FS_TICK   = 26
FS_LEGEND = 24

STRATEGY_LABELS = {
    "front_run":        "Front-Run (PoS)",
    "sandwich":         "Sandwich (PoS)",
    "arbitrage":        "Arbitrage (PoS)",
    "blind_insert_p2s": "Blind Insert (P2S)",
}

# Warm tones for PoS strategies (flare palette), cool tones for P2S (mako palette)
_FLARE = sns.color_palette("flare", n_colors=8)
_MAKO  = sns.color_palette("mako",  n_colors=8)
STRATEGY_COLORS = {
    "Front-Run (PoS)":    _FLARE[7],  # deep red
    "Sandwich (PoS)":     _FLARE[5],  # salmon
    "Arbitrage (PoS)":    _FLARE[3],  # amber
    "Blind Insert (P2S)": _MAKO[6],   # light teal
    "Block Stuffer (P2S)":_MAKO[4],   # medium blue
    "Arbitrage (P2S)":    _MAKO[2],   # deep blue
}

# Legend display: (section, display_name, STRATEGY_COLORS key)
_LEGEND_ENTRIES = [
    ("PoS", "Front-Run",    "Front-Run (PoS)"),
    ("PoS", "Sandwich",     "Sandwich (PoS)"),
    ("PoS", "Arbitrage",    "Arbitrage (PoS)"),
    ("P2S", "Blind Insert", "Blind Insert (P2S)"),
    ("P2S", "Block Stuffer","Block Stuffer (P2S)"),
    ("P2S", "Arbitrage",    "Arbitrage (P2S)"),
]


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

    # Local font sizes (this panel sits at ~half column width, side by side, so it
    # needs larger fonts than the standalone cost-gain figure that shares FS_*).
    _FL, _FT, _FLG = 20, 17, 16
    ax.set_xlim(0, n)
    ax.set_ylim(0)
    ax.set_xlabel("Block", fontsize=_FL, fontweight="bold")
    ax.set_ylabel("Cumulative MEV (ETH)", fontsize=_FL, fontweight="bold")
    ax.yaxis.set_label_coords(-0.135, 0.42)   # nudge the long y-label down so it does not overflow the top
    ax.tick_params(labelsize=_FT)
    ax.legend(fontsize=_FLG, loc="upper left", frameon=False)
    sns.despine(ax=ax)
    ax.grid(True, alpha=0.18, linestyle="--", color="gray")
    ax.set_axisbelow(True)


# ─────────────────────────────────────────────────────────────────────────────
# Panel: Cost vs Gain scatter per attack strategy
# ─────────────────────────────────────────────────────────────────────────────

def _panel_cost_gain(ax, block_ledger, p2s_agents):
    import pandas as pd
    import matplotlib.lines as mlines

    # Per-strategy, per-block (cost, gain) from the latest simulation results.
    # cost = the gas to mount the attack in THIS block (its gas units priced at the
    # block's own gas price, which varies 28-60 gwei across the cache), so cost
    # spreads horizontally instead of collapsing to one value per strategy; gain =
    # the realized per-block profit (heavy-tailed). Points on/above the dashed
    # gain=cost line are profitable, below it loss-making. Under P2S the content-
    # dependent strategies are structurally absent; only blind insertion remains,
    # and it sits well below break-even.
    repo = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if repo not in sys.path:
        sys.path.insert(0, repo)
    from scripts.simulation.environment import load_gas_prices
    results = sorted(glob.glob(os.path.join(repo, "data", "simulation_*.json")))
    records = []
    if results:
        with open(results[-1]) as f:
            R = json.load(f)
        sample = next(iter(R.get("attack_strategies", {}).values()), {})
        n_blocks = len(sample.get("per_block_gain_eth", [])) or 1000
        gp = load_gas_prices(n_blocks)                 # effective gwei per block
        mean_gp = sum(gp) / len(gp)
        for group in ("attack_strategies", "attack_strategies_p2s"):
            for strat, v in R.get(group, {}).items():
                label = STRATEGY_LABELS.get(strat)
                if label is None:
                    continue  # g-limit stuffing has no profit axis; see the stuffing figures
                cost0 = v.get("cost_per_attempt_eth", 0.0)  # gas units x mean gas price
                gains = v.get("per_block_gain_eth", [])
                for i, g in enumerate(gains):
                    if g > 0:
                        cost_i = cost0 * gp[i] / mean_gp     # this block's gas price
                        records.append({"Strategy": label, "cost": cost_i, "gain": g})

    df = pd.DataFrame(records)
    if df.empty:
        ax.text(0.5, 0.5, "no profitable attacks", transform=ax.transAxes,
                ha="center", va="center", fontsize=FS_LEGEND)
        return

    x_max = df["cost"].max() * 1.15
    y_max = df["gain"].max() * 1.15

    present = list(df["Strategy"].unique())
    sns.scatterplot(
        data=df, x="cost", y="gain", hue="Strategy",
        palette={k: STRATEGY_COLORS[k] for k in present},
        alpha=0.6, s=55, ax=ax, legend=False,
    )

    # Gains are heavy-tailed (small common sandwiches up to rare whales of ~1 ETH),
    # so the gain axis is logarithmic; the break-even line gain=cost is drawn over
    # the observed cost range.
    xs = np.linspace(df["cost"].min() * 0.8, x_max, 60)
    ax.plot(xs, xs, "--", color="gray", lw=1.4)

    def _circle(color, label):
        return mlines.Line2D([], [], marker="o", linestyle="None",
                             color=color, markersize=8, alpha=0.8, label=label)
    def _header(text):
        return mlines.Line2D([], [], color="none", linestyle="None", label=text)

    handles, current_section = [], None
    for section, name, key in _LEGEND_ENTRIES:
        if key not in present:
            continue
        if section != current_section:
            handles.append(_header(f"{section}:"))
            current_section = section
        handles.append(_circle(STRATEGY_COLORS[key], f"  {name}"))
    handles.append(mlines.Line2D([], [], color="gray", linestyle="--", label="gain = cost"))
    ax.legend(handles=handles, fontsize=FS_LEGEND - 4, loc="upper right",
              borderaxespad=0.4, frameon=False, labelspacing=0.3, handletextpad=0.3)

    ax.set_yscale("log")
    ax.set_xlim(0, x_max)
    ax.set_ylim(df["gain"].min() * 0.6, y_max * 1.4)
    ax.set_xlabel("Cost per attack (ETH)", fontsize=FS_LABEL, fontweight="bold")
    ax.set_ylabel("Gain per attack (ETH)", fontsize=FS_LABEL, fontweight="bold")
    ax.tick_params(labelsize=FS_TICK)
    sns.despine(ax=ax)
    ax.grid(True, alpha=0.18, linestyle="--", color="gray")
    ax.set_axisbelow(True)


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    repo_root   = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    data_dir    = os.path.join(repo_root, DATA_DIR)
    figures_dir = os.path.join(repo_root, FIGURES_DIR)

    # Per-block MEV series from the recalibrated block simulation (measured
    # magnitudes), so the cumulative panel shares one calibration with the rest.
    with open(os.path.join(data_dir, "mev_comparison.json")) as f:
        _pbg = json.load(f)["per_block_gain_eth"]
    pos_series, p2s_series, p2s_agents = _pbg["ethereum"], _pbg["p2s"], {}
    block_ledger = _load_block_ledger(data_dir)
    if block_ledger is None:
        print("No block_ledger_*.json found — cost/gain scatter will use only aggregate means.",
              file=sys.stderr)

    os.makedirs(figures_dir, exist_ok=True)
    sns.set_theme(style="ticks")

    # Figure (a): Cumulative MEV
    fig, ax = plt.subplots(figsize=(4.5, 3.8))
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
