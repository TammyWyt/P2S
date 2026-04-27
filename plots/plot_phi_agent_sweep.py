#!/usr/bin/env python3
"""
φ sweep figures — three separate PDFs:

  phi_agent_activity.pdf    — agent activity rate vs φ  (simulation, log x-axis)
  phi_agent_profit.pdf      — MEV profit vs φ  (simulation, MC)
  phi_gas_sensitivity.pdf   — B2ProposerBot activity rate vs φ at multiple gas prices (simulation)

Loads data/phi_experiments.json (run scripts/simulation/run_phi_experiments.py
to regenerate).

Run: python plots/plot_phi_agent_sweep.py
"""

import json
import os
import sys

import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd
import seaborn as sns

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, ".."))
sys.path.insert(0, _ROOT)

from scripts.simulation.constants import MEAN_GAS_GWEI, N_VALIDATORS

DATA_PATH   = os.path.join(_ROOT, "data", "phi_experiments.json")
FIGURES_DIR = os.path.join(_ROOT, "figures", "phi")

VLAG    = sns.color_palette("vlag", n_colors=10)
C_B2    = VLAG[-3]
C_STUFF = "goldenrod"

# Deactivation thresholds at MEAN_GAS_GWEI = 0.074 gwei (Base L2 post-Dencun mean)
PHI_STAR_STUFF = 0.26    # BlockStufferBot
PHI_STAR_B2    = 831.0   # B2ProposerBot

FS_LABEL  = 15
FS_TICK   = 13
FS_LEGEND = 11


def _save(fig: plt.Figure, name: str) -> None:
    os.makedirs(FIGURES_DIR, exist_ok=True)
    out = os.path.join(FIGURES_DIR, name)
    fig.savefig(out, dpi=300, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved → {out}")


# ─────────────────────────────────────────────────────────────────────────────
# phi_agent_activity.pdf
# ─────────────────────────────────────────────────────────────────────────────

def plot_activity(exp1: dict) -> None:
    phi_vals = exp1["phi_values"]
    b2_act   = exp1["activity"]["B2ProposerBot"]
    st_act   = exp1["activity"]["BlockStufferBot"]

    df_b2 = pd.DataFrame({"phi": phi_vals, "Activity rate": b2_act})

    fig, ax = plt.subplots(figsize=(7, 5))

    ax.axhline(1 / N_VALIDATORS, color="gray", lw=1.2, ls=":",
               alpha=0.7, zorder=1, label=r"Proposer rate $1/N_\mathrm{val}$")

    sns.lineplot(data=df_b2, x="phi", y="Activity rate",
                 color=C_B2, lw=2.5, marker="o", markersize=5, zorder=4,
                 label="B2 Proposer Bot", ax=ax)
    ax.step(phi_vals, st_act, where="post",
            color=C_STUFF, lw=2.0, ls="--", zorder=3,
            label="Block Stuffer Bot")

    ax.axvline(PHI_STAR_STUFF, color=C_STUFF, lw=1.3, ls="--", alpha=0.85, zorder=5,
               label=fr"$\varphi^*_{{\mathrm{{stuff}}}} = {PHI_STAR_STUFF}$")
    ax.axvline(PHI_STAR_B2, color=C_B2, lw=1.3, ls="--", alpha=0.85, zorder=5,
               label=fr"$\varphi^*_{{\mathrm{{B2}}}} = {PHI_STAR_B2:.0f}$")

    ax.set_xscale("log")
    ax.set_xlabel(r"Reservation-fee parameter $\varphi$ (log scale)",
                  fontsize=FS_LABEL, fontweight="bold")
    ax.set_ylabel("Agent activity rate", fontsize=FS_LABEL, fontweight="bold")
    ax.set_xlim(min(phi_vals), max(phi_vals) * 1.5)
    ax.set_ylim(-0.03, 1.03)
    ax.yaxis.set_major_formatter(mticker.PercentFormatter(xmax=1.0))
    ax.tick_params(labelsize=FS_TICK)
    ax.legend(fontsize=FS_LEGEND, loc="upper right", framealpha=0.92)
    sns.despine(ax=ax)
    plt.tight_layout()
    _save(fig, "phi_agent_activity.pdf")


# ─────────────────────────────────────────────────────────────────────────────
# phi_agent_profit.pdf
# ─────────────────────────────────────────────────────────────────────────────

def plot_profit(exp6: dict) -> None:
    phi_vals  = exp6["phi_values"]
    run_means = exp6["run_means"]

    mus, los, his = [], [], []
    for phi in phi_vals:
        arr = np.array(run_means[str(phi)])
        mus.append(float(np.mean(arr)))
        los.append(float(np.percentile(arr, 2.5)))
        his.append(float(np.percentile(arr, 97.5)))

    los = [max(v, 0.0) for v in los]
    mus = [max(v, 0.0) for v in mus]

    df = pd.DataFrame({"phi": phi_vals, "MEV profit (ETH)": mus})

    fig, ax = plt.subplots(figsize=(7, 5))

    ax.fill_between(phi_vals, los, his, color=C_B2, alpha=0.15, zorder=0,
                    label="95% CI (empirical)")
    sns.lineplot(data=df, x="phi", y="MEV profit (ETH)",
                 color=C_B2, lw=2.5, marker="o", markersize=5,
                 label="B2 Proposer Bot (simulation)", ax=ax, zorder=4)

    ax.axhline(0, color="gray", lw=0.8, ls="--", alpha=0.5)
    ax.axvline(PHI_STAR_B2, color=C_B2, lw=1.3, ls="--", alpha=0.85, zorder=5,
               label=fr"$\varphi^*_{{\mathrm{{B2}}}} = {PHI_STAR_B2:.0f}$")

    ax.set_xscale("log")
    ax.set_xlabel(r"Reservation-fee parameter $\varphi$ (log scale)",
                  fontsize=FS_LABEL, fontweight="bold")
    ax.set_ylabel("MEV profit (ETH)", fontsize=FS_LABEL, fontweight="bold")
    ax.set_xlim(min(phi_vals), max(phi_vals) * 1.5)
    ax.set_ylim(bottom=0)
    ax.tick_params(labelsize=FS_TICK)
    ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.4f"))
    ax.legend(fontsize=FS_LEGEND, loc="upper right", framealpha=0.92)
    sns.despine(ax=ax)
    plt.tight_layout()
    _save(fig, "phi_agent_profit.pdf")


# ─────────────────────────────────────────────────────────────────────────────
# phi_gas_sensitivity.pdf
# ─────────────────────────────────────────────────────────────────────────────

def plot_gas_sensitivity(exp4: dict) -> None:
    """
    B2ProposerBot activity rate vs φ at four Base L2 gas-price levels (simulation).
    Log x-axis — φ* shifts left as gas price rises.
    """
    gas_prices = exp4["gas_prices_gwei"]
    phi_vals   = exp4["phi_values"]
    b2_act     = exp4["b2_activity"]

    palette = {
        "0.005":            "#d62728",
        "0.02":             "#9467bd",
        str(MEAN_GAS_GWEI): "#1f77b4",
        "0.2":              "#2ca02c",
    }
    labels = {
        "0.005":            fr"$g^{{\mathsf{{base}}}} = 0.005$ gwei (floor)",
        "0.02":             fr"$g^{{\mathsf{{base}}}} = 0.02$ gwei",
        str(MEAN_GAS_GWEI): fr"$g^{{\mathsf{{base}}}} = {MEAN_GAS_GWEI}$ gwei (post-Dencun mean)",
        "0.2":              fr"$g^{{\mathsf{{base}}}} = 0.2$ gwei",
    }

    rows = []
    for gp in gas_prices:
        key = str(gp)
        for phi, act in zip(phi_vals, b2_act[key]):
            rows.append({"phi": phi, "Activity rate": act, "Gas price": key})
    df = pd.DataFrame(rows)

    fig, ax = plt.subplots(figsize=(7, 5))

    for gp in gas_prices:
        key = str(gp)
        if key not in palette:
            continue
        sub = df[df["Gas price"] == key]
        lw  = 2.8 if gp == MEAN_GAS_GWEI else 1.8
        sns.lineplot(data=sub, x="phi", y="Activity rate",
                     color=palette[key], lw=lw, marker="o", markersize=4,
                     label=labels[key], ax=ax, zorder=4)

    ax.axhline(1 / N_VALIDATORS, color="gray", lw=1.2, ls=":",
               alpha=0.7, zorder=1, label=r"Proposer rate $1/N_\mathrm{val}$")

    ax.set_xscale("log")
    ax.set_xlabel(r"Reservation-fee parameter $\varphi$ (log scale)",
                  fontsize=FS_LABEL, fontweight="bold")
    ax.set_ylabel("B2 Proposer Bot activity rate", fontsize=FS_LABEL, fontweight="bold")
    ax.set_xlim(min(phi_vals), max(phi_vals) * 1.5)
    ax.set_ylim(-0.03, 1.03)
    ax.yaxis.set_major_formatter(mticker.PercentFormatter(xmax=1.0))
    ax.tick_params(labelsize=FS_TICK)
    ax.legend(fontsize=FS_LEGEND, loc="upper right", framealpha=0.92)
    sns.despine(ax=ax)
    plt.tight_layout()
    _save(fig, "phi_gas_sensitivity.pdf")


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    if not os.path.exists(DATA_PATH):
        print(f"Missing {DATA_PATH}")
        print("Run: python scripts/simulation/run_phi_experiments.py")
        sys.exit(1)
    with open(DATA_PATH) as f:
        data = json.load(f)

    sns.set_theme(style="ticks")

    plot_activity(data["exp1_phi_sweep"])
    if "exp6_profit_mc" in data:
        plot_profit(data["exp6_profit_mc"])
    plot_gas_sensitivity(data["exp4_gas_activity"])


if __name__ == "__main__":
    main()
