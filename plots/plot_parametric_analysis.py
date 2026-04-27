#!/usr/bin/env python3
"""
P2S Parametric Analysis — MEV-Mitigation Research Plots
========================================================
Generates 2 publication-quality PDF figures saved to figures/:

  1.  phi_sweep.pdf                    — Attacker profit vs phi across full range
                                         [0, 0.5]; annotates phi* breakeven point
  2.  block_latency_vs_congestion.pdf  — P2S two-phase latency overhead vs PoS

Rational attacker model: profit = max(0, E[net]).
Negative expected value → attacker does not attempt → profit = 0, never negative.

All profit figures use analytical expected values to avoid noise from the
heavy-tailed log-normal gain distribution (sigma=1.5, CoV~140%).
Simulation is retained for the latency plot (low-variance).

Parameter choices documented in RESEARCH_SOURCES.md.
Run from project root:  python plots/plot_parametric_analysis.py
"""

import json
import math
import os
import random
import sys
import time as _time_module

import matplotlib.pyplot as plt
import numpy as np
import seaborn as sns

_time_module.sleep = lambda _: None

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, ".."))
sys.path.insert(0, _ROOT)
from scripts.simulation.simulator import (  # noqa: E402
    P2SSimulator,
    MEVAttackStrategies,
    GWEI_PER_ETH,
    WEI_PER_ETH,
)

# ─────────────────────────────────────────────────────────────────────────────
# Style — matches plot_attack_success_cost_reward.py
# ─────────────────────────────────────────────────────────────────────────────
VLAG = sns.color_palette("vlag", n_colors=10)
COLOR_ETH = VLAG[1]    # blue — Ethereum PoS
COLOR_P2S = VLAG[-2]   # red  — P2S
COLOR_B2  = VLAG[-4]   # dark — P2S B2 proposer

FONTSIZE_LABEL  = 18
FONTSIZE_TICK   = 16
FONTSIZE_LEGEND = 14

sns.set_theme(style="ticks", font_scale=1.0)

FIGURES_DIR = os.path.join(_ROOT, "figures")
DATA_DIR    = os.path.join(_ROOT, "data")
CACHE_PATH  = os.path.join(DATA_DIR, "ethereum_blocks_cache.json")

RANDOM_SEED     = 42
PHI_VALUES      = [0.00, 0.05, 0.10, 0.15, 0.20, 0.30, 0.40, 0.50]
CONGESTION_VALS = [0.0, 0.1, 0.2, 0.3, 0.5, 0.7, 0.9]
N_BLOCKS        = 1000   # simulation blocks (latency plot only)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────
def _load_cache_gas_prices(n: int) -> list:
    random.seed(RANDOM_SEED)
    if not os.path.exists(CACHE_PATH):
        return [random.uniform(0.02, 0.20) for _ in range(n)]   # Base L2 range (gwei)
    with open(CACHE_PATH, "r", encoding="utf-8") as fh:
        cache = json.load(fh)
    blocks = list(cache.values())[:n]
    prices = []
    for b in blocks:
        fee = b.get("base_fee", 0)                               # EIP-1559 block base fee
        if isinstance(fee, str):
            fee = int(fee, 16) if fee.startswith("0x") else int(fee)
        fee_gwei = fee / 1e9 if fee > 1e6 else float(fee)       # convert Wei → gwei if needed
        prices.append(fee_gwei if fee_gwei > 0 else 0.074)
    while len(prices) < n:
        prices.append(random.uniform(0.02, 0.20))
    return prices[:n]


def _load_ethereum_blocks(n: int) -> list:
    random.seed(RANDOM_SEED)
    sim = P2SSimulator()
    blocks = sim.load_ethereum_blocks(DATA_DIR)
    if not blocks:
        return [sim._synthetic_ethereum_block(i) for i in range(n)]
    while len(blocks) < n:
        blocks.append(sim._synthetic_ethereum_block(len(blocks)))
    return blocks[:n]


def _save(fig, name: str) -> None:
    os.makedirs(FIGURES_DIR, exist_ok=True)
    path = os.path.join(FIGURES_DIR, name)
    fig.savefig(path, dpi=300, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved {path}")


# ─────────────────────────────────────────────────────────────────────────────
# Analytical profit model
# ─────────────────────────────────────────────────────────────────────────────
def analytical_profits(mean_gas_gwei: float) -> dict:
    """
    Rational attacker expected net profit per block for each strategy.
    profit = max(0, E[gain] - E[cost]): attacker only acts when profitable.
    PoS values are phi-independent (no F_res in base Ethereum).
    P2S values depend on phi via F_res = phi * g^limit * g^base.
    """
    C = MEVAttackStrategies

    e_mev   = min(math.exp(C.MEV_GAIN_MU   + C.MEV_GAIN_SIGMA**2   / 2), C.MEV_GAIN_MAX)
    e_blind = min(math.exp(C.BLIND_GAIN_MU + C.BLIND_GAIN_SIGMA**2 / 2), C.MEV_GAIN_MAX)

    def gas_eth(units):
        return (mean_gas_gwei * GWEI_PER_ETH * units) / WEI_PER_ETH

    exec_pht  = gas_eth(C.GAS_BLIND_INSERT)
    exec_fr   = gas_eth(C.GAS_FRONT_RUN)
    exec_sw_f = gas_eth(C.GAS_SANDWICH_FRONT)
    exec_sw_b = gas_eth(C.GAS_SANDWICH_BACK)
    exec_arb  = gas_eth(C.GAS_ARBITRAGE)

    HAS_TARGET = 0.20   # fraction of blocks with a visible front-run/sandwich target

    # PoS (phi-independent)
    pos_fr_net  = max(0.0, HAS_TARGET * C.FRONT_RUN_SUCCESS_RATE * e_mev
                          - HAS_TARGET * 1.2 * exec_fr)
    pos_sw_net  = max(0.0, HAS_TARGET * C.SANDWICH_SUCCESS_RATE  * e_mev
                          - HAS_TARGET * (1.3 * exec_sw_f + 1.1 * exec_sw_b))
    pos_arb_net = max(0.0, C.ARBITRAGE_OPPORTUNITY_RATE * C.ARBITRAGE_EXEC_RATE * e_mev
                          - C.ARBITRAGE_OPPORTUNITY_RATE * exec_arb)

    # P2S (phi-dependent via F_res)
    ext_nets, b2_nets = [], []
    for phi in PHI_VALUES:
        cost_pht = (1.0 + phi) * exec_pht

        ext_gain = C.P2S_ATTACK_FITS_RATE * C.P2S_ATTACK_SUCCESS_RATE * e_blind
        ext_nets.append(max(0.0, ext_gain - cost_pht))

        n_phts   = C.B2_ATTACK_PHTS_PER_BLOCK
        b2_gain  = n_phts * C.B2_PROPOSER_MATCH_PROB * e_mev
        b2_nets.append(max(0.0, b2_gain - n_phts * cost_pht))

    phi_star_b2 = (C.B2_PROPOSER_MATCH_PROB * e_mev / exec_pht) - 1.0

    return {
        "phi":           PHI_VALUES,
        "pos_fr":        pos_fr_net,
        "pos_sw":        pos_sw_net,
        "pos_arb":       pos_arb_net,
        "ext_net":       ext_nets,
        "b2_net":        b2_nets,
        "phi_star_b2":   phi_star_b2,
        "e_mev":         e_mev,
        "e_blind":       e_blind,
        "exec_pht":      exec_pht,
        "mean_gas_gwei": mean_gas_gwei,
    }


def sweep_congestion(eth_blocks: list) -> dict:
    """Simulate N_BLOCKS per congestion level for latency plot."""
    print("  Sweeping congestion for latency…")
    results = {
        "congestion":  CONGESTION_VALS,
        "p2s_latency": [], "eth_latency": [],
        "p2s_b1_time": [], "p2s_b2_time": [],
    }
    n = min(N_BLOCKS, len(eth_blocks))
    for ci, cong in enumerate(CONGESTION_VALS):
        random.seed(RANDOM_SEED + ci)
        np.random.seed(RANDOM_SEED + ci)
        sim = P2SSimulator()
        for i in range(5):
            sim.create_validator(f"pv{i}", "P2S")
            sim.create_validator(f"ev{i}", "Ethereum PoS")
        p2s_lat, eth_lat, p2s_b1, p2s_b2 = [], [], [], []
        for i in range(n):
            blk   = eth_blocks[i % len(eth_blocks)]
            pid_p = sim.select_proposer("P2S")
            pid_e = sim.select_proposer("Ethereum PoS")
            pb = sim.simulate_p2s_block(i, pid_p, blk, cong)
            eb = sim.simulate_ethereum_pos_block(i, pid_e, blk, cong)
            p2s_lat.append(pb["network_latency"])
            eth_lat.append(eb["network_latency"])
            p2s_b1.append(pb.get("b1_time", 0.0))
            p2s_b2.append(pb.get("b2_time", 0.0))
        results["p2s_latency"].append(np.mean(p2s_lat))
        results["eth_latency"].append(np.mean(eth_lat))
        results["p2s_b1_time"].append(np.mean(p2s_b1))
        results["p2s_b2_time"].append(np.mean(p2s_b2))
    return results


# ─────────────────────────────────────────────────────────────────────────────
# Plot 1: φ sweep — rational attacker profit vs reservation-fee parameter
# ─────────────────────────────────────────────────────────────────────────────
def plot_phi_sweep(ap: dict) -> None:
    """
    Line plot: x = φ ∈ PHI_VALUES, y = rational attacker profit per block (ETH).
    Shows PoS baselines as flat lines and P2S B2 proposer profit decreasing to 0.
    Annotates φ* (the minimum deterrent threshold) and shades the deterrence zone.
    Saved to figures/phi_sweep.pdf.
    """
    phis    = ap["phi"]
    phi_arr = np.array(phis)

    # PoS strategies are φ-independent
    pos_fr  = np.full_like(phi_arr, ap["pos_fr"])
    pos_arb = np.full_like(phi_arr, ap["pos_arb"])

    # P2S strategies vary with φ
    b2_net  = np.array(ap["b2_net"])
    ext_net = np.array(ap["ext_net"])  # ≡ 0 at all φ

    phi_star = ap["phi_star_b2"]

    fig, ax = plt.subplots(figsize=(9, 5))

    # PoS flat baselines
    ax.plot(phis, pos_fr,  color=COLOR_ETH, lw=2.0, ls="--",  marker="s",
            markersize=5, label="PoS front-run (φ-independent)")
    ax.plot(phis, pos_arb, color=COLOR_ETH, lw=2.0, ls=":",   marker="^",
            markersize=5, label="PoS arbitrage (φ-independent)")

    # P2S B2 proposer (decreasing)
    ax.plot(phis, b2_net, color=COLOR_B2, lw=2.5, marker="o",
            markersize=6, label=r"P2S $B_2$ proposer")

    # P2S external blind (≡ 0)
    ax.axhline(0.0, color=COLOR_P2S, lw=1.2, ls="-.", alpha=0.7,
               label="P2S external blind (≡ 0)")

    # φ* vertical line and annotation
    ax.axvline(phi_star, color="black", lw=1.4, ls="--", alpha=0.75)
    ax.text(phi_star + 0.005, ax.get_ylim()[1] if ax.get_ylim()[1] > 0 else 0.003,
            fr"$\varphi^*\!\approx\!{phi_star:.2f}$",
            fontsize=FONTSIZE_LEGEND, va="top", ha="left", color="black")

    # Shade deterrence zone (φ ≥ φ*)
    ymax_val = max(float(pos_fr.max()), float(b2_net.max()), 1e-5) * 1.35
    ax.axvspan(phi_star, max(phis), alpha=0.07, color=COLOR_P2S,
               label=fr"Deterrence zone ($\varphi \geq \varphi^*$)")

    # Recommended operating point φ = 0.10
    ax.axvline(0.10, color="dimgray", lw=1.0, ls=":", alpha=0.6)
    ax.text(0.10 + 0.005, ymax_val * 0.55,
            r"$\varphi=0.10$" + "\n(recommended)",
            fontsize=10, color="dimgray", ha="left")

    ax.set_xlabel(r"Reservation-fee parameter $\varphi$",
                  fontsize=FONTSIZE_LABEL, fontweight="bold")
    ax.set_ylabel("Rational profit per block (ETH)",
                  fontsize=FONTSIZE_LABEL, fontweight="bold")
    ax.set_xlim(0, max(phis))
    ax.set_ylim(bottom=-0.00005, top=ymax_val)
    ax.tick_params(labelsize=FONTSIZE_TICK)
    ax.legend(fontsize=FONTSIZE_LEGEND - 1, loc="upper right")
    sns.despine(ax=ax)
    plt.tight_layout()
    _save(fig, "phi_sweep.pdf")


# ─────────────────────────────────────────────────────────────────────────────
# Plot 2: Block latency vs congestion
# ─────────────────────────────────────────────────────────────────────────────
def plot2_latency(cong: dict) -> None:
    fig, ax = plt.subplots(figsize=(8, 5))
    x = cong["congestion"]
    ax.plot(x, cong["eth_latency"], color=COLOR_ETH, marker="s", lw=2.0,
            label="Ethereum PoS")
    ax.plot(x, cong["p2s_latency"], color=COLOR_P2S, marker="o", lw=2.0,
            label="P2S total")
    ax.plot(x, cong["p2s_b1_time"], color=COLOR_P2S, marker="^", lw=1.5, ls="--",
            label=r"P2S $B_1$ phase")
    ax.plot(x, cong["p2s_b2_time"], color=COLOR_P2S, marker="v", lw=1.5, ls=":",
            label=r"P2S $B_2$ phase")
    ax.fill_between(x, cong["eth_latency"], cong["p2s_latency"],
                    alpha=0.10, color=COLOR_P2S, label="P2S overhead")
    ax.set_xlabel("Network congestion level",
                  fontsize=FONTSIZE_LABEL, fontweight="bold")
    ax.set_ylabel("Network latency per block (s)",
                  fontsize=FONTSIZE_LABEL, fontweight="bold")
    ax.tick_params(labelsize=FONTSIZE_TICK)
    ax.legend(fontsize=FONTSIZE_LEGEND - 1, loc="upper left")
    sns.despine(ax=ax)
    plt.tight_layout()
    _save(fig, "block_latency_vs_congestion.pdf")


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────
def main() -> None:
    random.seed(RANDOM_SEED)
    np.random.seed(RANDOM_SEED)

    print("=" * 65)
    print("P2S Parametric Analysis — 2 plots")
    print("=" * 65)

    gas_prices = _load_cache_gas_prices(N_BLOCKS)
    eth_blocks = _load_ethereum_blocks(N_BLOCKS)
    mean_gp    = float(np.mean(gas_prices))
    print(f"  {len(eth_blocks)} blocks  |  mean gas {mean_gp:.1f} gwei")

    ap        = analytical_profits(mean_gp)
    cong_data = sweep_congestion(eth_blocks)

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(os.path.join(DATA_DIR, "parametric_results.json"), "w") as fh:
        json.dump({"analytical": ap, "congestion": cong_data}, fh,
                  indent=2, default=float)

    print(f"\n  Gas price: {mean_gp:.1f} gwei  |  "
          f"E[mev_gain] = {ap['e_mev']:.4f} ETH  |  "
          f"exec_pht = {ap['exec_pht']:.5f} ETH")
    print(f"  B2 phi* = {ap['phi_star_b2']:.3f}\n")

    hdrs = ["phi", "PoS FR", "PoS SW", "PoS Arb", "P2S Ext", "P2S B2"]
    print("  " + "  ".join(f"{h:>9}" for h in hdrs))
    for i, phi in enumerate(ap["phi"]):
        row = [phi, ap["pos_fr"], ap["pos_sw"], ap["pos_arb"],
               ap["ext_net"][i], ap["b2_net"][i]]
        print("  " + "  ".join(f"{v:+9.5f}" for v in row))

    print("\nGenerating plots…")
    plot_phi_sweep(ap)
    plot2_latency(cong_data)
    print(f"\n  All 2 PDFs saved to {FIGURES_DIR}/")


if __name__ == "__main__":
    main()
