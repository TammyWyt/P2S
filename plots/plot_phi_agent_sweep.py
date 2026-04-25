#!/usr/bin/env python3
"""
φ sweep figures — three separate PDFs:

  phi_agent_activity.pdf    — agent activity rate vs φ  (simulation)
  phi_agent_profit.pdf      — expected net profit vs φ  (analytical)
  phi_gas_sensitivity.pdf   — deterrence threshold φ* vs base fee

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
import seaborn as sns

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, ".."))
sys.path.insert(0, _ROOT)

from scripts.simulation.constants import (
    MEAN_GAS_GWEI, E_MEV_GAIN, B2_MATCH_PROB, B2_N_PHTS, N_VALIDATORS,
    GAS_PHT, STUFF_E_BENEFIT, STUFF_N_PHTS, STUFF_GAS_DECLARED,
)
from scripts.simulation.environment import gas_eth

DATA_PATH   = os.path.join(_ROOT, "data", "phi_experiments.json")
FIGURES_DIR = os.path.join(_ROOT, "figures", "phi")

VLAG    = sns.color_palette("vlag", n_colors=10)
C_B2    = VLAG[-3]
C_STUFF = "goldenrod"
C_REC   = "dimgray"

PHI_STAR = 0.052
PHI_REC  = 0.10

FS_LABEL  = 15   # axis labels
FS_TICK   = 13   # tick labels
FS_LEGEND = 11   # legend


# ─────────────────────────────────────────────────────────────────────────────
# Analytical helpers
# ─────────────────────────────────────────────────────────────────────────────

def _b2_net_ueth(phi: float, gp: float = MEAN_GAS_GWEI) -> float:
    margin = B2_MATCH_PROB * E_MEV_GAIN - gas_eth(gp, GAS_PHT) * (1 + phi)
    return max((B2_N_PHTS / N_VALIDATORS) * margin * 1e6, 0.0)


def _stuffer_net_ueth(phi: float, gp: float = MEAN_GAS_GWEI) -> float:
    return max(STUFF_E_BENEFIT - STUFF_N_PHTS * phi * gas_eth(gp, STUFF_GAS_DECLARED), 0.0) * 1e6


def _phi_star_b2(gp: float) -> float:
    return B2_MATCH_PROB * E_MEV_GAIN / gas_eth(gp, GAS_PHT) - 1.0


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

    fig, ax = plt.subplots(figsize=(7, 5))

    ax.axvspan(PHI_STAR, 0.15, color="#d4edda", alpha=0.45, zorder=0,
               label=r"Safe zone ($\varphi > \varphi^*$)")

    ax.axhline(1 / N_VALIDATORS, color="gray", lw=1.2, ls=":",
               alpha=0.7, zorder=1, label=r"Proposer rate $1/N_\mathrm{val}$")

    ax.plot(phi_vals, b2_act,
            color=C_B2, lw=2.5, ls="-", marker="o", markersize=5, zorder=4,
            label="B2 Proposer Bot")
    ax.step(phi_vals, st_act, where="post",
            color=C_STUFF, lw=2.0, ls="--", zorder=3,
            label="Block Stuffer Bot")

    ax.axvline(PHI_STAR, color="black", lw=1.3, ls="--", alpha=0.75, zorder=5,
               label=fr"$\varphi^* = {PHI_STAR}$")
    ax.axvline(PHI_REC, color=C_REC, lw=1.2, ls=":", alpha=0.8, zorder=5,
               label=fr"$\varphi = {PHI_REC}$ (recommended)")

    ax.set_xlabel(r"Reservation-fee parameter $\varphi$",
                  fontsize=FS_LABEL, fontweight="bold")
    ax.set_ylabel("Agent activity rate", fontsize=FS_LABEL, fontweight="bold")
    ax.set_xlim(0, 0.15)
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

def plot_profit() -> None:
    phi_dense = np.linspace(0, 0.15, 500)
    b2_curve  = [_b2_net_ueth(p) for p in phi_dense]
    st_curve  = [_stuffer_net_ueth(p) for p in phi_dense]

    fig, ax = plt.subplots(figsize=(7, 5))

    ax.fill_between(phi_dense, 0, b2_curve, color=C_B2, alpha=0.10, zorder=0)
    ax.plot(phi_dense, b2_curve, color=C_B2, lw=2.5,
            label="B2 Proposer Bot", zorder=4)
    ax.plot(phi_dense, st_curve, color=C_STUFF, lw=2.0, ls="--",
            label="Block Stuffer Bot", zorder=3)

    ax.axhline(0, color="gray", lw=0.8, ls="--", alpha=0.5)
    ax.axvline(PHI_STAR, color="black", lw=1.3, ls="--", alpha=0.75, zorder=5,
               label=fr"$\varphi^* = {PHI_STAR}$")
    ax.axvline(PHI_REC, color=C_REC, lw=1.2, ls=":", alpha=0.8, zorder=5,
               label=fr"$\varphi = {PHI_REC}$ (recommended)")

    ax.set_xlabel(r"Reservation-fee parameter $\varphi$",
                  fontsize=FS_LABEL, fontweight="bold")
    ax.set_ylabel(r"E[net profit] per block ($\mu$ETH)",
                  fontsize=FS_LABEL, fontweight="bold")
    ax.set_xlim(0, 0.15)
    ax.set_ylim(bottom=-5)
    ax.tick_params(labelsize=FS_TICK)
    ax.legend(fontsize=FS_LEGEND, loc="upper right", framealpha=0.92)
    sns.despine(ax=ax)
    plt.tight_layout()
    _save(fig, "phi_agent_profit.pdf")


# ─────────────────────────────────────────────────────────────────────────────
# phi_gas_sensitivity.pdf
# ─────────────────────────────────────────────────────────────────────────────

def plot_gas_sensitivity() -> None:
    gp_dense = np.linspace(15, 120, 600)
    ps_curve = [_phi_star_b2(g) for g in gp_dense]

    fig, ax = plt.subplots(figsize=(7, 5))

    ax.fill_between(gp_dense, ps_curve, PHI_REC,
                    where=[p > PHI_REC for p in ps_curve],
                    color="#f8d7da", alpha=0.7, zorder=0,
                    label=r"$\varphi^* > 0.10$: fee insufficient")
    ax.fill_between(gp_dense, 0, [min(p, PHI_REC) for p in ps_curve],
                    where=[p > 0 for p in ps_curve],
                    color="#fff3cd", alpha=0.7, zorder=0,
                    label=r"$0 < \varphi^* \leq 0.10$: recommended fee covers attack")
    ax.fill_between(gp_dense, ps_curve, 0,
                    where=[p < 0 for p in ps_curve],
                    color="#d4edda", alpha=0.6, zorder=0,
                    label=r"$\varphi^* < 0$: attack unprofitable without fee")

    ax.plot(gp_dense, ps_curve, color=C_B2, lw=2.5, zorder=4)
    ax.axhline(0, color="gray", lw=0.8, ls="--", alpha=0.5)
    ax.axhline(PHI_REC, color=C_REC, lw=1.2, ls=":", alpha=0.8, zorder=5,
               label=fr"$\varphi = {PHI_REC}$ (recommended)")
    ax.axvline(MEAN_GAS_GWEI, color="black", lw=1.3, ls="--", alpha=0.75, zorder=5,
               label=fr"Empirical mean $\bar{{g}} = {MEAN_GAS_GWEI:.0f}$ gwei")

    ax.set_xlabel("Base fee (gwei)", fontsize=FS_LABEL, fontweight="bold")
    ax.set_ylabel(r"Deterrence threshold $\varphi^*$",
                  fontsize=FS_LABEL, fontweight="bold")
    ax.set_xlim(15, 120)
    ax.set_ylim(-0.45, 1.15)
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
    plot_profit()
    plot_gas_sensitivity()


if __name__ == "__main__":
    main()
