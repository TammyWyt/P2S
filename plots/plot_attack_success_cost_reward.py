#!/usr/bin/env python3
"""
Design evaluation figure (Figure 7): two panels that together evaluate P2S.

  (a) Cumulative MEV extraction over 1,000 blocks — line plot showing the
      sustained extraction rate under Ethereum PoS vs P2S.

  (b) Attack profitability scatter — each attack strategy is a bubble:
        x = total cost invested (ETH)
        y = total gain extracted (ETH)
        size = success rate (%)
      A diagonal breakeven line (y = x) separates profitable from unprofitable
      attacks. Iso-ROI curves show relative profitability.

Data sources:
  - data/p2s_mev_attacks.json    (panel a: per-block MEV series)
  - data/simulation_*.json        (panel b: per-strategy cost/gain/success)

Output: figures/mev_design_evaluation.pdf
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

VLAG        = sns.color_palette("vlag", n_colors=10)
COLOR_ETH   = VLAG[1]
COLOR_P2S   = VLAG[-2]

FS_LABEL  = 13
FS_TICK   = 12
FS_LEGEND = 11
FS_ANNOT  = 10


# ─────────────────────────────────────────────────────────────────────────────
# Data loaders
# ─────────────────────────────────────────────────────────────────────────────

def _load_mev_series(data_dir: str):
    path = os.path.join(data_dir, "p2s_mev_attacks.json")
    if not os.path.isfile(path):
        return None
    with open(path) as f:
        d = json.load(f)
    pos = d.get("baseline_pos_mev", [])
    p2s = d.get("baseline_p2s_mev", [])
    return pos, p2s


def _load_simulation(data_dir: str):
    files = glob.glob(os.path.join(data_dir, "simulation_*.json"))
    if not files:
        return None, None
    path = max(files, key=os.path.getmtime)
    with open(path) as f:
        return json.load(f), path


# ─────────────────────────────────────────────────────────────────────────────
# Panel (a): Cumulative MEV extraction curves
# ─────────────────────────────────────────────────────────────────────────────

def _panel_cumulative(ax, pos_series, p2s_series):
    n = min(len(pos_series), len(p2s_series))
    blocks = np.arange(1, n + 1)
    cum_pos = np.cumsum(pos_series[:n])
    cum_p2s = np.cumsum(p2s_series[:n])

    ax.plot(blocks, cum_pos, color=COLOR_ETH, lw=2.0, label="Ethereum PoS")
    ax.plot(blocks, cum_p2s, color=COLOR_P2S, lw=2.0, label="P2S")
    ax.fill_between(blocks, cum_p2s, cum_pos, alpha=0.12, color=COLOR_P2S)

    final_pos = cum_pos[-1]
    final_p2s = cum_p2s[-1]
    reduction  = 100.0 * (final_pos - final_p2s) / final_pos if final_pos > 0 else 0

    # Endpoint annotations
    ax.annotate(f"{final_pos:.0f} ETH",
                xy=(n, final_pos), xytext=(-55, 6),
                textcoords="offset points", fontsize=FS_ANNOT,
                color=COLOR_ETH, fontweight="bold")
    ax.annotate(f"{final_p2s:.0f} ETH",
                xy=(n, final_p2s), xytext=(-55, -14),
                textcoords="offset points", fontsize=FS_ANNOT,
                color=COLOR_P2S, fontweight="bold")

    # Reduction bracket
    mid = n * 0.75
    ax.annotate("", xy=(mid, final_p2s * 0.5 + final_pos * 0.5),
                xytext=(mid, final_pos * 0.92),
                arrowprops=dict(arrowstyle="<->", color="dimgray", lw=1.0))
    ax.text(mid + n * 0.01, (final_p2s * 0.5 + final_pos * 0.5 + final_pos * 0.92) / 2,
            f"−{reduction:.0f}%\nMEV", fontsize=FS_ANNOT, color="dimgray", va="center")

    ax.set_xlabel("Block index", fontsize=FS_LABEL, fontweight="bold")
    ax.set_ylabel("Cumulative MEV extracted (ETH)", fontsize=FS_LABEL, fontweight="bold")
    ax.tick_params(labelsize=FS_TICK)
    ax.legend(fontsize=FS_LEGEND, loc="upper left")
    ax.text(0.02, 0.97, "(a)", transform=ax.transAxes,
            fontsize=13, fontweight="bold", va="top")
    sns.despine(ax=ax)


# ─────────────────────────────────────────────────────────────────────────────
# Panel (b): Attack profitability scatter
# ─────────────────────────────────────────────────────────────────────────────

def _panel_scatter(ax, sim_data):
    eth_strats = sim_data.get("attack_strategies", {})
    p2s_strats = sim_data.get("attack_strategies_p2s", {})

    points = []
    for name, s in eth_strats.items():
        attempts  = s.get("attempts") or 1
        successes = s.get("successes") or 0
        points.append({
            "label":    name.replace("_", " ").title(),
            "cost":     s.get("total_cost_eth") or 0,
            "gain":     s.get("total_gain_eth") or 0,
            "success":  100.0 * successes / attempts,
            "color":    COLOR_ETH,
            "marker":   "o",
        })
    for name, s in p2s_strats.items():
        attempts  = s.get("attempts") or 1
        successes = s.get("successes") or 0
        label = (name.replace("_", " ").replace("p2s", "")
                     .strip().title() or "Blind Insert")
        points.append({
            "label":    label,
            "cost":     s.get("total_cost_eth") or 0,
            "gain":     s.get("total_gain_eth") or 0,
            "success":  100.0 * successes / attempts,
            "color":    COLOR_P2S,
            "marker":   "^",
        })

    costs   = [p["cost"] for p in points]
    gains   = [p["gain"] for p in points]
    maxval  = max(max(costs), max(gains)) * 1.18

    # Iso-ROI reference lines
    xs = np.linspace(0, maxval, 200)
    ax.plot(xs, xs,       color="gray",   lw=1.0, ls="--",  alpha=0.6,
            label="Breakeven (0% ROI)")
    ax.plot(xs, 2 * xs,   color="gray",   lw=0.8, ls=":",   alpha=0.4,
            label="200% ROI")
    ax.plot(xs, 5 * xs,   color="gray",   lw=0.8, ls="-.",  alpha=0.3)
    ax.text(maxval * 0.52, maxval * 0.52 * 1.04, "y = x",
            fontsize=9, color="gray", alpha=0.7)
    ax.text(maxval * 0.52, maxval * 0.52 * 2.04, "2×",
            fontsize=9, color="gray", alpha=0.5)

    # Shade profitable region
    ax.fill_between(xs, xs, maxval, alpha=0.04, color=COLOR_ETH)
    ax.text(maxval * 0.05, maxval * 0.85, "Profitable\n(gain > cost)",
            fontsize=9, color="dimgray", alpha=0.6)

    # Scatter points — size proportional to success rate
    for p in points:
        size = max(p["success"] ** 2 * 18, 60)
        ax.scatter(p["cost"], p["gain"],
                   s=size, color=p["color"], marker=p["marker"],
                   edgecolors="white", linewidths=0.8, zorder=5, alpha=0.9)
        offset_x = maxval * 0.015
        offset_y = maxval * 0.02
        ax.annotate(
            f"{p['label']}\n({p['success']:.0f}% success)",
            xy=(p["cost"], p["gain"]),
            xytext=(p["cost"] + offset_x, p["gain"] + offset_y),
            fontsize=9, color=p["color"],
        )

    # Custom legend for protocol
    from matplotlib.lines import Line2D
    legend_elements = [
        Line2D([0], [0], marker="o", color="w", markerfacecolor=COLOR_ETH,
               markersize=9, label="Ethereum PoS"),
        Line2D([0], [0], marker="^", color="w", markerfacecolor=COLOR_P2S,
               markersize=9, label="P2S"),
        Line2D([0], [0], color="gray", lw=1.0, ls="--", label="Breakeven"),
    ]
    ax.legend(handles=legend_elements, fontsize=FS_LEGEND, loc="upper left")

    ax.set_xlabel("Total cost invested (ETH)", fontsize=FS_LABEL, fontweight="bold")
    ax.set_ylabel("Total gain extracted (ETH)", fontsize=FS_LABEL, fontweight="bold")
    ax.set_xlim(0, maxval)
    ax.set_ylim(0, maxval)
    ax.tick_params(labelsize=FS_TICK)
    ax.text(0.02, 0.97, "(b)", transform=ax.transAxes,
            fontsize=13, fontweight="bold", va="top")
    sns.despine(ax=ax)


# ─────────────────────────────────────────────────────────────────────────────
# Main figure
# ─────────────────────────────────────────────────────────────────────────────

def plot_design_evaluation(data_dir: str, figures_dir: str) -> None:
    mev_series = _load_mev_series(data_dir)
    sim_data, sim_path = _load_simulation(data_dir)

    if mev_series is None or sim_data is None:
        print("Missing data files. Run simulation scripts first.", file=sys.stderr)
        sys.exit(1)

    print(f"Using {os.path.basename(sim_path)}")

    sns.set_theme(style="ticks")
    fig, (ax_a, ax_b) = plt.subplots(1, 2, figsize=(13, 5))

    _panel_cumulative(ax_a, mev_series[0], mev_series[1])
    _panel_scatter(ax_b, sim_data)

    plt.tight_layout()
    os.makedirs(figures_dir, exist_ok=True)
    out = os.path.join(figures_dir, "mev_design_evaluation.pdf")
    plt.savefig(out, dpi=300, bbox_inches="tight")
    plt.close()
    print(f"Saved {out}")


def main():
    repo_root   = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    data_dir    = os.path.join(repo_root, DATA_DIR)
    figures_dir = os.path.join(repo_root, FIGURES_DIR)
    plot_design_evaluation(data_dir, figures_dir)


if __name__ == "__main__":
    main()
