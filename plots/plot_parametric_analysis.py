#!/usr/bin/env python3
"""
P2S Parametric Analysis — MEV-Mitigation Research Plots
========================================================
Generates 2 publication-quality PDF figures:

  1.  block_latency_vs_congestion.pdf  — P2S two-phase latency overhead vs PoS
  2.  gas_squat_vs_phi.pdf             — Gas-squat deterrence via F_res vs phi

Rational attacker model: an attacker only executes a strategy when E[profit] > 0.
All profit values are clamped to max(0, E[net]).  Negative expected value → attacker
does not attempt the attack → profit = 0 (not negative).

All profit figures use analytical expected values (not simulated averages) to avoid
noise from the heavy-tailed gain distribution (sigma=1.5 gives CoV~140%).
Simulation is retained for the latency plot (latency is low-variance).

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
sys.path.insert(0, os.path.join(_ROOT, "scripts", "testing"))
from simulation import (  # noqa: E402
    P2SSimulator,
    MEVAttackStrategies,
    ETH_MAINNET_BLOCK_GAS_LIMIT,
    GWEI_PER_ETH,
    WEI_PER_ETH,
)

# ─────────────────────────────────────────────────────────────────────────────
# Style — matches plot_attack_success_cost_reward.py
# ─────────────────────────────────────────────────────────────────────────────
VLAG = sns.color_palette("vlag", n_colors=10)
COLOR_ETH = VLAG[1]   # blue  — Ethereum PoS
COLOR_P2S = VLAG[-2]  # red   — P2S

FONTSIZE_LABEL  = 18
FONTSIZE_TICK   = 16
FONTSIZE_LEGEND = 14

sns.set_theme(style="ticks", font_scale=1.0)

FIGURES_DIR = _HERE
DATA_DIR    = os.path.join(_ROOT, "data")
CACHE_PATH  = os.path.join(DATA_DIR, "ethereum_blocks_cache.json")

RANDOM_SEED = 42

PHI_VALUES      = [0.00, 0.05, 0.10, 0.15, 0.20, 0.30, 0.40, 0.50]
CONGESTION_VALS = [0.0, 0.1, 0.2, 0.3, 0.5, 0.7, 0.9]
N_BLOCKS = 1000   # simulation blocks (latency plot only)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────
def _load_cache_gas_prices(n: int) -> list:
    random.seed(RANDOM_SEED)
    if not os.path.exists(CACHE_PATH):
        return [random.uniform(15, 60) for _ in range(n)]
    with open(CACHE_PATH, "r", encoding="utf-8") as fh:
        cache = json.load(fh)
    blocks = list(cache.values())[:n]
    prices = []
    for b in blocks:
        txs = b.get("transactions", [])
        if txs:
            gp = txs[0].get("gasPrice", 20e9)
            if isinstance(gp, (int, float)) and gp > 1e9:
                gp /= 1e9
            prices.append(float(gp) if gp > 0 else 20.0)
        else:
            prices.append(20.0)
    while len(prices) < n:
        prices.append(random.uniform(15, 60))
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
    path = os.path.join(FIGURES_DIR, name)
    fig.savefig(path, dpi=300, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved {name}")


# ─────────────────────────────────────────────────────────────────────────────
# Analytical profit model
# ─────────────────────────────────────────────────────────────────────────────
def analytical_profits(mean_gas_gwei: float) -> dict:
    """
    Compute rational attacker expected net profit per block for every strategy.
    A rational attacker only executes when E[net] > 0: profit = max(0, E[net]).

    All costs assume the attacker only submits a transaction when an opportunity
    exists (zero cost otherwise).  Gas costs scale with mean_gas_gwei.

    Strategies:
      PoS front-run   — profitable when target visible (20% of blocks)
      PoS sandwich    — two-legged; higher gas cost per attempt
      PoS arbitrage   — cross-DEX; own opportunity detection (15% of blocks)
      P2S external    — blind PHT; low success rate; usually not profitable

    Returns per-phi vectors; PoS values are phi-independent (no F_res).
    """
    C = MEVAttackStrategies   # alias

    # Expected gains (log-normal means)
    e_mev   = min(math.exp(C.MEV_GAIN_MU   + C.MEV_GAIN_SIGMA**2   / 2), C.MEV_GAIN_MAX)
    e_blind = min(math.exp(C.BLIND_GAIN_MU + C.BLIND_GAIN_SIGMA**2 / 2), C.MEV_GAIN_MAX)

    def gas_eth(units): return (mean_gas_gwei * GWEI_PER_ETH * units) / WEI_PER_ETH

    exec_pht  = gas_eth(C.GAS_BLIND_INSERT)
    exec_fr   = gas_eth(C.GAS_FRONT_RUN)
    exec_sw_f = gas_eth(C.GAS_SANDWICH_FRONT)
    exec_sw_b = gas_eth(C.GAS_SANDWICH_BACK)
    exec_arb  = gas_eth(C.GAS_ARBITRAGE)

    HAS_TARGET = 0.20   # fraction of blocks with a sandwich/front-run target

    # PoS: phi-independent
    fr_gain_pb  = HAS_TARGET * C.FRONT_RUN_SUCCESS_RATE * e_mev
    fr_cost_pb  = HAS_TARGET * 1.2 * exec_fr
    sw_gain_pb  = HAS_TARGET * C.SANDWICH_SUCCESS_RATE  * e_mev
    sw_cost_pb  = HAS_TARGET * (1.3 * exec_sw_f + 1.1 * exec_sw_b)
    arb_gain_pb = C.ARBITRAGE_OPPORTUNITY_RATE * C.ARBITRAGE_EXEC_RATE * e_mev
    arb_cost_pb = C.ARBITRAGE_OPPORTUNITY_RATE * exec_arb

    pos_fr_net  = max(0.0, fr_gain_pb  - fr_cost_pb)
    pos_sw_net  = max(0.0, sw_gain_pb  - sw_cost_pb)
    pos_arb_net = max(0.0, arb_gain_pb - arb_cost_pb)

    # P2S: phi-dependent via F_res
    ext_nets = []
    for phi in PHI_VALUES:
        cost_pht = (1.0 + phi) * exec_pht

        # External blind insert
        ext_gain = C.P2S_ATTACK_FITS_RATE * C.P2S_ATTACK_SUCCESS_RATE * e_blind
        ext_nets.append(max(0.0, ext_gain - cost_pht))

    return {
        "phi":          PHI_VALUES,
        "pos_fr":       pos_fr_net,   # scalar (phi-independent)
        "pos_sw":       pos_sw_net,
        "pos_arb":      pos_arb_net,
        "ext_net":      ext_nets,
        "e_mev":        e_mev,
        "e_blind":      e_blind,
        "exec_pht":     exec_pht,
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
# Plot functions
# ─────────────────────────────────────────────────────────────────────────────

def plot2_latency(cong: dict) -> None:
    """Plot 2: Block finality latency vs congestion."""
    fig, ax = plt.subplots(figsize=(8, 5))
    x = cong["congestion"]
    ax.plot(x, cong["eth_latency"], color=COLOR_ETH, marker="s", lw=2.0,
            label="Ethereum PoS")
    ax.plot(x, cong["p2s_latency"], color=COLOR_P2S, marker="o", lw=2.0,
            label="P2S total")
    ax.plot(x, cong["p2s_b1_time"], color=COLOR_P2S, marker="^", lw=1.5, ls="--",
            label="P2S B1 phase")
    ax.plot(x, cong["p2s_b2_time"], color=COLOR_P2S, marker="v", lw=1.5, ls=":",
            label="P2S B2 phase")
    ax.fill_between(x, cong["eth_latency"], cong["p2s_latency"],
                    alpha=0.10, color=COLOR_P2S, label="P2S overhead")
    ax.set_xlabel("Network congestion level", fontsize=FONTSIZE_LABEL, fontweight="bold")
    ax.set_ylabel("Network latency per block (s)", fontsize=FONTSIZE_LABEL, fontweight="bold")
    ax.tick_params(labelsize=FONTSIZE_TICK)
    ax.legend(fontsize=FONTSIZE_LEGEND - 1, loc="upper left")
    sns.despine(ax=ax)
    plt.tight_layout()
    _save(fig, "block_latency_vs_congestion.pdf")


SQUAT_MULTIPLIERS = [1, 2, 3, 5, 10, 20, 50]
GAS_SQUAT_GMAX_RATIOS = [1.5, 2.0, 3.0]


def plot3_gas_squat_vs_phi() -> None:
    """
    Deterrence threshold for gas-squat attacks.

    An attacker inflates g^limit = k × g^used.  With F_res the effective cost
    per unit of g^used becomes g^base × (1 + φ·k).  The attacker is constrained
    by g^max (maxFeePerGas): deterred when g^base × (1 + φ·k) > g^max, i.e.

        φ*(k) = (g^max / g^base − 1) / k

    Each curve shows φ*(k) for a different g^max / g^base ratio.
    """
    x   = SQUAT_MULTIPLIERS
    grn = ["#1b7837", "#4d9221", "#b8e186"]

    fig, ax = plt.subplots(figsize=(8, 5))

    for bi, (ratio, col) in enumerate(zip(GAS_SQUAT_GMAX_RATIOS, grn)):
        y = [(ratio - 1.0) / k for k in x]
        ax.plot(x, y, color=col, lw=2.0, marker="o", ms=5,
                label=r"$g^{\mathsf{max}} = %.1f \times g^{\mathsf{base}}$" % ratio)
        ax.fill_between(x, y, 0.60, alpha=0.07, color=col)

    ax.axhline(0.10, color=COLOR_P2S, lw=1.5, ls="--",
               label=r"$\varphi = 0.10$ (default)")
    ax.set_xlabel("Gas-limit inflation multiplier k",
                  fontsize=FONTSIZE_LABEL - 2, fontweight="bold")
    ax.set_ylabel(r"Minimum $\varphi$ to deter squatting",
                  fontsize=FONTSIZE_LABEL - 2, fontweight="bold")
    ax.set_ylim(0, 0.60)
    ax.tick_params(labelsize=FONTSIZE_TICK - 1)
    ax.legend(fontsize=FONTSIZE_LEGEND - 1)
    sns.despine(ax=ax)
    plt.tight_layout()
    _save(fig, "gas_squat_vs_phi.pdf")


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
          f"exec_pht = {ap['exec_pht']:.5f} ETH\n")

    hdrs = ["phi", "PoS FR", "PoS SW", "PoS Arb", "P2S Ext"]
    print("  " + "  ".join(f"{h:>9}" for h in hdrs))
    for i, phi in enumerate(ap["phi"]):
        row = [phi, ap["pos_fr"], ap["pos_sw"], ap["pos_arb"],
               ap["ext_net"][i]]
        print("  " + "  ".join(f"{v:+9.5f}" for v in row))

    print("\nGenerating plots…")
    plot2_latency(cong_data)
    plot3_gas_squat_vs_phi()

    print(f"\n  All 2 PDFs saved to {FIGURES_DIR}/")


if __name__ == "__main__":
    main()
