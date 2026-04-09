#!/usr/bin/env python3
"""
P2S MEV Attack Simulation — Smart Attacker Models
==================================================
Simulates MEV attacks in Ethereum PoS and P2S using algorithm-driven
smart attackers on the SAME per-block transaction pool.

Core model
----------
1. AMM pool state (Angeris 2021 exact CFMM sandwich profit formula)
   profit* = (√(r + Δ_v) - √r)²; pool reserve mean-reverts across blocks.

2. Rational attacker threshold
   Attackers fire ONLY when E[net profit] > 0 (Daian 2020 PGA equilibrium).

3. Bayesian gas-limit inference for P2S
   PHTs expose g_limit only; overlapping gas ranges create genuine Bayesian
   uncertainty (~28% miss rate; ~10% FP rate at θ=0.5).

4. Greedy B2 proposer scheduler (Flashbots-style)
   Proposer sorts revealed MTs by sandwich profit, fires in 1/n_validators blocks.

Experiments
-----------
  EXP-1  Baseline 1000-block run at default parameters
  EXP-4  Pool-liquidity sweep  [100, 300, 500, 1000, 3000, 5000] ETH

Attack taxonomy
---------------
PoS (full mempool visibility):
  POS-SW   PGA sandwich      Daian et al. IEEE S&P 2020
  POS-ARB  CFMM arbitrage    Angeris et al. CES 2021; Qin et al. arXiv:2101.05511

P2S (only g_limit visible from PHT in B1):
  P2S-INF  Gas-limit Bayesian inference sandwich
  P2S-B2   B2 proposer greedy MEV scheduler (1/n_validators blocks)
  P2S-ARB  Cross-block CFMM arb (post-B2 reveal)

Outputs (figures/)
------------------
  mev_cdf.pdf               EXP-1: per-block MEV CDF (PoS vs P2S)
  mev_vs_pool_liquidity.pdf EXP-4: MEV vs AMM pool depth

Run:  python plots/plot_p2s_mev_attacks.py
"""

import json
import math
import os
import random
import sys
from dataclasses import dataclass
from typing import List, Tuple

import matplotlib.pyplot as plt
import numpy as np
import seaborn as sns

# ── Paths ─────────────────────────────────────────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, ".."))
sys.path.insert(0, os.path.join(_ROOT, "scripts", "testing"))
from simulation import GWEI_PER_ETH, WEI_PER_ETH  # noqa: E402

FIGURES_DIR = os.path.join(_ROOT, "figures")
DATA_DIR    = os.path.join(_ROOT, "data")
CACHE_PATH  = os.path.join(DATA_DIR, "ethereum_blocks_cache.json")

# ── Style ─────────────────────────────────────────────────────────────────────
VLAG  = sns.color_palette("vlag", n_colors=10)
C_ETH = VLAG[1]    # blue — PoS
C_P2S = VLAG[-2]   # red  — P2S
sns.set_theme(style="ticks", font_scale=1.0)
FS_L, FS_T, FS_G = 18, 16, 14

# ── Simulation constants ───────────────────────────────────────────────────────
RANDOM_SEED        = 42
N_BLOCKS           = 1000   # baseline run
N_SWEEP_BLOCKS     = 400    # blocks per pool-sweep point

DEFAULT_PHI          = 0.10
DEFAULT_N_VALIDATORS = 5
DEFAULT_POOL_ETH     = 1_000.0

POOL_SWEEP_ETH = [100, 300, 500, 1_000, 3_000, 5_000]

# Gas constants
GAS_SW_FRONT = 200_000
GAS_SW_BACK  = 150_000
GAS_ARB      = 300_000
GAS_PHT      = 200_000
GAS_B2_PHT   = 150_000

# Gain calibration: median sandwich ≈ 0.015 ETH at r=1000 ETH (Torres 2024)
GAIN_CAP  = 2.0

# PGA bidding premiums (Daian 2020)
PREM_FRONT = 1.30
PREM_BACK  = 1.10

# Attacker success rates (Torres 2024, Qin 2021)
SW_SUCCESS = 0.35
ARB_OPP    = 0.15
ARB_EXEC   = 0.60
ARB_EFF    = 0.80

# P2S B2 proposer
B2_N_PHTS = 5

# P2S cross-block arb
XB_OPP  = 0.10
XB_EXEC = 0.70
XB_EFF  = 0.75

# P2S inference: INF_EXEC × INF_DIR = 0.50 × 0.55 ≈ 0.275 (Torres 2024)
INF_EXEC     = 0.50
INF_DIR      = 0.55
INF_SUCC     = INF_EXEC * INF_DIR
INF_MAX_PHTS = 20

# Victim trade sizes: lognormal calibrated to Torres (2024)
TRADE_MU  = math.log(5.5)
TRADE_SIG = 1.2
TRADE_CAP = 200.0


# ═════════════════════════════════════════════════════════════════════════════
# 1. AMM pool
# ═════════════════════════════════════════════════════════════════════════════

class AMMPool:
    """
    Constant-product AMM pool with exact Angeris (2021) sandwich profit:
        profit* = (√(r + Δ_v) - √r)²
    Pool reserve mean-reverts across blocks (κ=0.30, Qin 2021).
    """
    REVERT_SPEED = 0.30
    NOISE_STD    = 0.04

    def __init__(self, reserve_eth: float = DEFAULT_POOL_ETH):
        self.r0 = reserve_eth
        self.r  = reserve_eth

    def sandwich_profit(self, victim_trade_eth: float) -> float:
        if victim_trade_eth <= 0 or self.r <= 0:
            return 0.0
        return min((math.sqrt(self.r + victim_trade_eth) - math.sqrt(self.r)) ** 2, GAIN_CAP)

    def next_block(self) -> None:
        shock  = random.gauss(0, self.NOISE_STD) * self.r
        self.r = max(self.r + self.REVERT_SPEED * (self.r0 - self.r) + shock, 10.0)


# ═════════════════════════════════════════════════════════════════════════════
# 2. Transaction pool
# ═════════════════════════════════════════════════════════════════════════════

ETH_TX  = "eth_transfer"
ERC20   = "erc20"
DEX     = "dex_swap"
COMPLEX = "complex"

TX_PRIORS = {ETH_TX: 0.30, ERC20: 0.20, DEX: 0.35, COMPLEX: 0.15}

# Overlapping gas ranges create genuine Bayesian ambiguity (EIP-2028; Uniswap docs; Qin 2021)
GAS_RANGES = {
    ETH_TX:  (21_000,   25_000),
    ERC20:   (45_000,  130_000),   # overlaps DEX at 80–130k
    DEX:     (80_000,  260_000),
    COMPLEX: (180_000, 600_000),   # overlaps DEX at 180–260k
}


@dataclass
class Tx:
    tx_type:        str
    gas_limit:      int
    gas_price_gwei: float
    trade_eth:      float = 0.0

    @property
    def is_dex(self) -> bool:
        return self.tx_type == DEX


def _make_tx(gp: float) -> Tx:
    tx_type = random.choices(list(TX_PRIORS), weights=list(TX_PRIORS.values()))[0]
    lo, hi  = GAS_RANGES[tx_type]
    trade   = min(random.lognormvariate(TRADE_MU, TRADE_SIG), TRADE_CAP) if tx_type == DEX else 0.0
    return Tx(tx_type, random.randint(lo, hi), gp, trade)


def build_txpool(gp: float, n: int) -> List[Tx]:
    return [_make_tx(gp) for _ in range(n)]


def gas_eth(gwei: float, units: int) -> float:
    return (gwei * GWEI_PER_ETH * units) / WEI_PER_ETH


# ═════════════════════════════════════════════════════════════════════════════
# 3. Bayesian gas-limit classifier
# ═════════════════════════════════════════════════════════════════════════════

class BayesGasClassifier:
    """
    P(DEX swap | g_limit) via Bayesian inference on observed PHT gas limits.
    Precision ≈ 90%, recall ≈ 72% at θ=0.5 (overlapping gas ranges create
    an information-theoretic floor; Torres 2024).
    """
    THRESHOLD = 0.50

    def p_swap(self, gas_limit: int) -> float:
        num = den = 0.0
        for tx_type, prior in TX_PRIORS.items():
            lo, hi = GAS_RANGES[tx_type]
            if lo <= gas_limit <= hi:
                w    = prior / max(hi - lo, 1)
                den += w
                if tx_type == DEX:
                    num += w
        return (num / den) if den > 0 else 0.0

    def should_attack(self, gas_limit: int) -> bool:
        return self.p_swap(gas_limit) >= self.THRESHOLD


_clf = BayesGasClassifier()


# ═════════════════════════════════════════════════════════════════════════════
# 4. PoS attackers
# ═════════════════════════════════════════════════════════════════════════════

def pos_sandwich_block(txpool: List[Tx], pool: AMMPool, gp: float) -> Tuple[float, float, int]:
    """PGA sandwich on all DEX swaps; rational threshold per bot (Daian 2020, Torres 2024)."""
    cost_sw    = gas_eth(gp * PREM_FRONT, GAS_SW_FRONT) + gas_eth(gp * PREM_BACK, GAS_SW_BACK)
    total_gain = total_cost = 0.0
    n_hits = 0
    for tx in txpool:
        if not tx.is_dex:
            continue
        max_gain = pool.sandwich_profit(tx.trade_eth)
        if SW_SUCCESS * max_gain <= cost_sw:
            continue
        total_cost += cost_sw
        if random.random() < SW_SUCCESS:
            total_gain += max_gain
            n_hits += 1
    return total_cost, total_gain, n_hits


def pos_arb_block(txpool: List[Tx], pool: AMMPool, gp: float) -> Tuple[float, float, bool]:
    """CFMM cross-pool arb; 15% opportunity rate, 60% exec (Angeris 2021, Qin 2021)."""
    if random.random() >= ARB_OPP:
        return 0.0, 0.0, False
    cost  = gas_eth(gp, GAS_ARB)
    swaps = [t for t in txpool if t.is_dex]
    if not swaps:
        return cost, 0.0, False
    max_gain = pool.sandwich_profit(max(swaps, key=lambda t: t.trade_eth).trade_eth) * ARB_EFF
    if ARB_EXEC * max_gain <= cost:
        return 0.0, 0.0, False
    if random.random() >= ARB_EXEC:
        return cost, 0.0, False
    return cost, max_gain, True


# ═════════════════════════════════════════════════════════════════════════════
# 5. P2S attackers
# ═════════════════════════════════════════════════════════════════════════════

def p2s_inference_block(txpool: List[Tx], pool: AMMPool, gp: float, phi: float) -> Tuple[float, float, int]:
    """
    Gas-limit inference sandwich (B1 phase).
    Attacker uses Bayesian classifier on g_limit; pays F_res = φ×g_limit×g_base
    unconditionally.  Combined success = INF_EXEC × INF_DIR ≈ 0.275.
    """
    cost_per_pht = gas_eth(gp, GAS_PHT) * (1.0 + phi)
    e_trade      = math.exp(TRADE_MU + TRADE_SIG ** 2 / 2)
    if INF_SUCC * pool.sandwich_profit(e_trade) <= cost_per_pht:
        return 0.0, 0.0, 0

    candidates = sorted(
        [(t, _clf.p_swap(t.gas_limit)) for t in txpool if _clf.should_attack(t.gas_limit)],
        key=lambda x: x[1], reverse=True,
    )[:INF_MAX_PHTS]

    total_cost = total_gain = 0.0
    n_ok = 0
    for tx, _ in candidates:
        total_cost += cost_per_pht
        if tx.is_dex and random.random() < INF_SUCC:
            total_gain += pool.sandwich_profit(tx.trade_eth)
            n_ok += 1
    return total_cost, total_gain, n_ok


def p2s_b2_proposer_block(
    txpool: List[Tx], pool: AMMPool, gp: float, phi: float, n_validators: int
) -> Tuple[float, float, int]:
    """
    B2 proposer greedy MEV scheduler.
    Fires with prob 1/n_validators; sees all MTs before finalising B2;
    greedy-selects top B2_N_PHTS victims; achieves 100% success (controls ordering).
    Sources: Flashbots (2023); Yang et al. arXiv:2407.13931.
    """
    if random.random() >= 1.0 / n_validators:
        return 0.0, 0.0, 0
    total_cost = B2_N_PHTS * gas_eth(gp, GAS_B2_PHT) * (1.0 + phi)
    targets    = sorted(
        (t for t in txpool if t.is_dex),
        key=lambda t: pool.sandwich_profit(t.trade_eth), reverse=True,
    )[:B2_N_PHTS]
    total_gain = sum(pool.sandwich_profit(t.trade_eth) for t in targets)
    if total_gain <= total_cost:
        return 0.0, 0.0, 0
    return total_cost, total_gain, len(targets)


def p2s_xb_arb_block(txpool: List[Tx], pool: AMMPool, gp: float, phi: float) -> Tuple[float, float, bool]:
    """
    Cross-block arb: pre-commits PHT in B1, decides reveal after B2.
    Fewer opps (10% vs 15%) but no mempool race (70% exec vs 60%).
    """
    if random.random() >= XB_OPP:
        return 0.0, 0.0, False
    cost  = gas_eth(gp, GAS_ARB) * (1.0 + phi)
    swaps = [t for t in txpool if t.is_dex]
    if not swaps:
        return cost, 0.0, False
    max_gain = pool.sandwich_profit(max(swaps, key=lambda t: t.trade_eth).trade_eth) * XB_EFF
    if XB_EXEC * max_gain <= cost:
        return 0.0, 0.0, False
    if random.random() >= XB_EXEC:
        return cost, 0.0, False
    return cost, max_gain, True


# ═════════════════════════════════════════════════════════════════════════════
# 6. Per-block runners
# ═════════════════════════════════════════════════════════════════════════════

def run_pos_block(txpool: List[Tx], pool: AMMPool, gp: float) -> dict:
    sw_cost,  sw_gain,  sw_hits = pos_sandwich_block(txpool, pool, gp)
    arb_cost, arb_gain, arb_ok  = pos_arb_block(txpool, pool, gp)
    return {
        "sandwich":  {"mev": sw_gain,  "cost": sw_cost,  "hits": sw_hits},
        "arbitrage": {"mev": arb_gain, "cost": arb_cost, "hits": int(arb_ok)},
        "total_mev":   sw_gain  + arb_gain,
        "total_cost":  sw_cost  + arb_cost,
        "net_profit":  (sw_gain + arb_gain) - (sw_cost + arb_cost),
        "victim_loss": sw_gain,
    }


def run_p2s_block(txpool: List[Tx], pool: AMMPool, gp: float, phi: float, n_validators: int) -> dict:
    inf_cost, inf_gain, inf_hits = p2s_inference_block(txpool, pool, gp, phi)
    b2_cost,  b2_gain,  b2_hits  = p2s_b2_proposer_block(txpool, pool, gp, phi, n_validators)
    xb_cost,  xb_gain,  xb_ok   = p2s_xb_arb_block(txpool, pool, gp, phi)
    return {
        "inference":     {"mev": inf_gain, "cost": inf_cost, "hits": inf_hits},
        "b2_proposer":   {"mev": b2_gain,  "cost": b2_cost,  "hits": b2_hits},
        "cross_blk_arb": {"mev": xb_gain,  "cost": xb_cost,  "hits": int(xb_ok)},
        "total_mev":   inf_gain + b2_gain + xb_gain,
        "total_cost":  inf_cost + b2_cost + xb_cost,
        "net_profit":  (inf_gain + b2_gain + xb_gain) - (inf_cost + b2_cost + xb_cost),
        "victim_loss": inf_gain + b2_gain,
    }


# ═════════════════════════════════════════════════════════════════════════════
# 7. Simulation runner
# ═════════════════════════════════════════════════════════════════════════════

def load_gas_prices(n: int) -> List[float]:
    random.seed(RANDOM_SEED)
    if not os.path.exists(CACHE_PATH):
        return [random.uniform(15, 60) for _ in range(n)]
    with open(CACHE_PATH, encoding="utf-8") as fh:
        cache = json.load(fh)
    prices = []
    for b in list(cache.values())[:n]:
        txs = b.get("transactions", [])
        gp  = txs[0].get("gasPrice", 20e9) if txs else 20e9
        gp  = float(gp) / 1e9 if gp > 1e9 else float(gp)
        prices.append(max(gp, 1.0))
    while len(prices) < n:
        prices.append(random.uniform(15, 60))
    return prices[:n]


def simulate(
    n_blocks:     int   = N_BLOCKS,
    phi:          float = DEFAULT_PHI,
    n_validators: int   = DEFAULT_N_VALIDATORS,
    pool_eth:     float = DEFAULT_POOL_ETH,
    seed_offset:  int   = 0,
) -> dict:
    """Run n_blocks for both PoS and P2S on the SAME txpool each block."""
    random.seed(RANDOM_SEED + seed_offset)
    np.random.seed(RANDOM_SEED + seed_offset)
    gas_prices = load_gas_prices(n_blocks)
    pool       = AMMPool(pool_eth)

    pos_blocks: List[dict] = []
    p2s_blocks: List[dict] = []

    for i in range(n_blocks):
        gp     = gas_prices[i % len(gas_prices)]
        txpool = build_txpool(gp, random.randint(50, 200))
        pos_blocks.append(run_pos_block(txpool, pool, gp))
        p2s_blocks.append(run_p2s_block(txpool, pool, gp, phi, n_validators))
        pool.next_block()

    def smry(blocks: List[dict], keys: List[str]) -> dict:
        return {k: float(np.mean([b[k] for b in blocks])) for k in keys}

    def strat_smry(blocks: List[dict], strats: List[str]) -> dict:
        return {s: {"mean_mev":  float(np.mean([b[s]["mev"]  for b in blocks])),
                    "mean_cost": float(np.mean([b[s]["cost"] for b in blocks])),
                    "mean_hits": float(np.mean([b[s]["hits"] for b in blocks]))}
                for s in strats}

    top = ["total_mev", "total_cost", "net_profit", "victim_loss"]
    return {
        "params":      {"n_blocks": n_blocks, "phi": phi,
                        "n_validators": n_validators, "pool_eth": pool_eth},
        "pos_raw":     {k: [b[k] for b in pos_blocks] for k in top},
        "p2s_raw":     {k: [b[k] for b in p2s_blocks] for k in top},
        "pos_summary": {**smry(pos_blocks, top),
                        "strategies": strat_smry(pos_blocks, ["sandwich", "arbitrage"])},
        "p2s_summary": {**smry(p2s_blocks, top),
                        "strategies": strat_smry(
                            p2s_blocks, ["inference", "b2_proposer", "cross_blk_arb"])},
    }


# ═════════════════════════════════════════════════════════════════════════════
# 8. Pool-liquidity sweep (EXP-4)
# ═════════════════════════════════════════════════════════════════════════════

def sweep_pool_liquidity(n_blocks: int = N_SWEEP_BLOCKS) -> dict:
    print(f"  EXP-4 pool sweep ({len(POOL_SWEEP_ETH)} points × {n_blocks} blocks)…")
    rows = []
    for pool_eth in POOL_SWEEP_ETH:
        r = simulate(n_blocks, phi=DEFAULT_PHI,
                     n_validators=DEFAULT_N_VALIDATORS,
                     pool_eth=pool_eth, seed_offset=300)
        rows.append({
            "pool_eth":  pool_eth,
            "pos_mev":   r["pos_summary"]["total_mev"],
            "p2s_mev":   r["p2s_summary"]["total_mev"],
            "pos_victim":r["pos_summary"]["victim_loss"],
            "p2s_victim":r["p2s_summary"]["victim_loss"],
        })
        print(f"    pool={pool_eth:6.0f} ETH  PoS={rows[-1]['pos_mev']:.5f}  "
              f"P2S={rows[-1]['p2s_mev']:.5f}")
    return {"pool_sweep": rows}


# ═════════════════════════════════════════════════════════════════════════════
# 9. Plots
# ═════════════════════════════════════════════════════════════════════════════

def _save(fig, name: str) -> None:
    os.makedirs(FIGURES_DIR, exist_ok=True)
    path = os.path.join(FIGURES_DIR, name)
    fig.savefig(path, dpi=300, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved {path}")


def plot_cdf(baseline: dict) -> None:
    """EXP-1: per-block MEV CDF for PoS vs P2S."""
    pos_mev = np.array(baseline["pos_raw"]["total_mev"])
    p2s_mev = np.array(baseline["p2s_raw"]["total_mev"])

    fig, ax = plt.subplots(figsize=(9, 6))
    for arr, color, lbl in [
        (pos_mev, C_ETH, "Ethereum PoS"),
        (p2s_mev, C_P2S, fr"P2S ($\varphi={DEFAULT_PHI}$)"),
    ]:
        srt = np.sort(arr)
        cdf = np.arange(1, len(srt) + 1) / len(srt)
        ax.plot(srt, cdf, color=color, lw=2.5, label=lbl)
        ax.axvline(float(np.mean(arr)), color=color, lw=1.2, ls="--", alpha=0.6,
                   label=f"mean = {np.mean(arr):.4f} ETH")

    ax.set_xlabel("MEV extracted per block (ETH)", fontsize=FS_L, fontweight="bold")
    ax.set_ylabel("CDF", fontsize=FS_L, fontweight="bold")
    ax.tick_params(labelsize=FS_T)
    ax.legend(fontsize=FS_G - 1)
    sns.despine(ax=ax)
    plt.tight_layout()
    _save(fig, "mev_cdf.pdf")


def plot_pool_sweep(data: dict) -> None:
    """EXP-4: MEV vs AMM pool depth."""
    rows = data["pool_sweep"]
    pool = [r["pool_eth"] for r in rows]
    pos  = [r["pos_mev"]  for r in rows]
    p2s  = [r["p2s_mev"]  for r in rows]

    fig, ax = plt.subplots(figsize=(9, 6))
    ax.plot(pool, pos, color=C_ETH, marker="s", lw=2.5, label="Ethereum PoS")
    ax.plot(pool, p2s, color=C_P2S, marker="o", lw=2.5, label="P2S")
    ax.fill_between(pool, p2s, pos, alpha=0.12, color=C_P2S, label="MEV reduction gap")
    ax.set_xlabel("AMM pool liquidity (ETH)", fontsize=FS_L, fontweight="bold")
    ax.set_ylabel("Mean MEV per block (ETH)", fontsize=FS_L, fontweight="bold")
    ax.tick_params(labelsize=FS_T)
    ax.set_xlim(0, max(pool))
    ax.set_ylim(bottom=0)
    ax.legend(fontsize=FS_G)
    sns.despine(ax=ax)
    plt.tight_layout()
    _save(fig, "mev_vs_pool_liquidity.pdf")


# ═════════════════════════════════════════════════════════════════════════════
# 10. Main
# ═════════════════════════════════════════════════════════════════════════════

def main() -> None:
    print("=" * 65)
    print("P2S MEV Attack Simulation — Smart Attacker Models")
    print(f"  φ={DEFAULT_PHI}  n_validators={DEFAULT_N_VALIDATORS}  "
          f"pool={DEFAULT_POOL_ETH:.0f} ETH")
    print("=" * 65)

    # EXP-1: Baseline
    print(f"\nEXP-1  Baseline ({N_BLOCKS} blocks)…")
    baseline = simulate(N_BLOCKS)
    ps  = baseline["pos_summary"]
    p2s = baseline["p2s_summary"]

    print(f"\n  {'Strategy':<32} {'PoS':>12} {'P2S':>12}")
    print("  " + "-" * 58)
    for label, pv, p2v in [
        ("POS-SW  Sandwich (PGA)",     ps["strategies"]["sandwich"]["mean_mev"],       0.0),
        ("POS-ARB CFMM arbitrage",     ps["strategies"]["arbitrage"]["mean_mev"],      0.0),
        ("P2S-INF Gas-limit inference",0.0, p2s["strategies"]["inference"]["mean_mev"]),
        ("P2S-B2  Proposer scheduler", 0.0, p2s["strategies"]["b2_proposer"]["mean_mev"]),
        ("P2S-ARB Cross-block arb.",   0.0, p2s["strategies"]["cross_blk_arb"]["mean_mev"]),
    ]:
        print(f"  {label:<32} {pv:>10.5f} ETH  {p2v:>10.5f} ETH")
    print("  " + "-" * 58)
    print(f"  {'TOTAL MEV':<32} {ps['total_mev']:>10.5f} ETH  {p2s['total_mev']:>10.5f} ETH")
    print(f"  {'Victim loss':<32} {ps['victim_loss']:>10.5f} ETH  {p2s['victim_loss']:>10.5f} ETH")
    mev_red = (1 - p2s["total_mev"] / ps["total_mev"]) * 100 if ps["total_mev"] > 0 else 0
    print(f"\n  MEV reduction: {mev_red:.1f}%")

    # EXP-4: Pool sweep
    print()
    pool_data = sweep_pool_liquidity()

    # Save data
    os.makedirs(DATA_DIR, exist_ok=True)
    all_data = {
        "baseline_pos_mev": baseline["pos_raw"]["total_mev"],
        "baseline_p2s_mev": baseline["p2s_raw"]["total_mev"],
        "baseline":         {k: v for k, v in baseline.items()
                             if k not in ("pos_raw", "p2s_raw")},
        **pool_data,
    }
    with open(os.path.join(DATA_DIR, "p2s_mev_attacks.json"), "w") as fh:
        json.dump(all_data, fh, indent=2, default=float)

    # Generate plots
    print("\nGenerating plots…")
    plot_cdf(baseline)
    plot_pool_sweep(pool_data)
    print(f"\n  2 PDFs saved to {FIGURES_DIR}/")


if __name__ == "__main__":
    main()
