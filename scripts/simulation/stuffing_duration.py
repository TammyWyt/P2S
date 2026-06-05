"""
Sustained block-stuffing (DDoS) experiment.

Reframes the block stuffer as a *budget-bounded denial-of-service* attacker that
holds the chain to censor a time-sensitive target (a Fomo3D-style game, a bridge
withdrawal window, a liquidation, an oracle update), rather than an MEV-profit
monopolist.  The metric is therefore not profit but **attack duration**: given a
fixed budget B (ETH), how many consecutive blocks can the attacker keep every
other transaction out, and how does that compare to Ethereum mainnet today?

Three regimes share the same EIP-1559 base-fee update (environment.next_base_fee)
but differ in what gas signal drives it and what the attacker pays per block:

  ethereum    — the attacker executes real fill transactions, so the block sits
                at the 30M gas limit (200% of the 15M target) and the base fee
                rises +12.5%/block.  Per-block cost = (base+tip) * 30M gas.  The
                cost grows geometrically, so duration grows only LOGARITHMICALLY
                in the budget.  This is the self-limiting defence that makes
                sustained stuffing economically hopeless on mainnet today.

  p2s_static  — content-agnostic P2S with a FLAT reservation fee phi.  Dummy PHTs
                only *reserve* g^limit in B1 and reveal no MT, so B2 executes ~0
                gas.  The EIP-1559 base fee, keyed on executed gas, DECAYS toward
                the floor, so the reservation cost F_res = phi * G_block * base_fee
                gets CHEAPER every block.  Duration grows ~LINEARLY in the budget:
                P2S is strictly worse than Ethereum against sustained stuffing.

  p2s_dynamic — the proposed fix.  A reservation base fee bf_res follows EIP-1559
                dynamics keyed on the REVEAL GAP: the fraction u of reserved gas
                whose MT never appears in B2, against a benign no-show target u*.
                A pure stuffer (u = 1) raises bf_res +12.5%/block, so the
                reservation cost grows geometrically and duration returns to
                LOGARITHMIC in the budget — while benign congestion (full B1,
                everyone reveals, u ~ u*) never escalates the fee.

  p2s_adaptive— the evasion attack on p2s_dynamic.  The stuffer reveals a
                fraction r of its dummy reservations to suppress u = 1 - r, but
                must then EXECUTE that gas in B2, feeding the ordinary execution
                base fee: it escalates for r > 0.5 while the reservation fee
                escalates for r < 1 - u*.  The regions overlap, so every r leaves
                at least one fee growing geometrically; the sweep takes the
                worst case (max duration) over a grid of r per budget.

Run directly to (re)generate data/stuffing_duration.json:
    python -m scripts.simulation.stuffing_duration
"""

import json
import os
from typing import Dict, List

import numpy as np

from .constants import PRIORITY_FEE_GWEI
from .environment import (
    GAS_LIMIT_BLOCK, GAS_TARGET, BASE_FEE_FLOOR,
    gas_eth, next_base_fee, median_base_fee,
)

# Recommended reservation-fee ratio from the parametric analysis.
PHI_REC      = 0.20
SLOT_SECONDS = 12          # Ethereum slot time; blocks -> wall-clock seconds
REGIMES      = ("ethereum", "p2s_static", "p2s_dynamic", "p2s_adaptive")

# Reveal-gap reservation fee parameters.
U_TARGET   = 0.10                                 # benign no-show target u*
MAX_CHANGE = 0.125                                # per-block bound (EIP-1559 family)
ADAPTIVE_R_GRID  = (0.0, 0.25, 0.5, 0.6, 0.75, 0.9, 1.0)   # evader reveal fractions
ADAPTIVE_R_WORST = 0.6     # large-budget worst case, used for the cost trajectory


def next_reservation_fee(bf_res: float, u: float,
                         u_target: float = U_TARGET,
                         floor: float = BASE_FEE_FLOOR) -> float:
    """Reveal-gap update: escalate when the unrevealed fraction u exceeds u*."""
    delta = MAX_CHANGE * (u - u_target) / (1.0 - u_target)
    return max(floor, bf_res * (1.0 + delta))

_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data")


def _per_block_cost(regime: str, bf: float, bf_res: float, phi: float) -> float:
    """ETH the attacker burns to monopolise one block under each regime."""
    if regime == "ethereum":
        # Execute real fill transactions: pay (base + competitive tip) on the
        # full 30M-gas block.  The base-fee term is what escalates.
        return gas_eth(bf + PRIORITY_FEE_GWEI, GAS_LIMIT_BLOCK)
    if regime == "p2s_static":
        # Flat reservation fee on the fully-reserved block; B2 never executes.
        return phi * gas_eth(bf, GAS_LIMIT_BLOCK)
    if regime == "p2s_dynamic":
        # Reservation fee priced off the reveal-gap reservation base fee.
        return phi * gas_eth(bf_res, GAS_LIMIT_BLOCK)
    raise ValueError(f"unknown regime: {regime}")


def _advance_fees(regime: str, bf: float, bf_res: float):
    """Update the (execution, reservation) base fees for the next block."""
    if regime == "ethereum":
        # Full block (200% of target) -> +12.5% on the execution base fee.
        return next_base_fee(bf, GAS_LIMIT_BLOCK), bf_res
    if regime == "p2s_static":
        # B2 executes ~0 gas -> execution base fee decays -12.5% toward floor.
        return next_base_fee(bf, 0.0), bf_res
    if regime == "p2s_dynamic":
        # Pure stuffer reveals nothing (u = 1) -> +12.5% on bf_res.
        return bf, next_reservation_fee(bf_res, 1.0)
    raise ValueError(f"unknown regime: {regime}")


def simulate_duration(budget_eth: float, regime: str, phi: float = PHI_REC,
                      bf0: float = None, max_blocks: int = 1_000_000) -> int:
    """Blocks the attacker can keep fully stuffed before the budget is exhausted."""
    if bf0 is None:
        bf0 = median_base_fee()
    bf, bf_res = bf0, bf0
    budget = budget_eth
    blocks = 0
    while blocks < max_blocks:
        cost = _per_block_cost(regime, bf, bf_res, phi)
        # Fast path: once p2s_static has decayed to the base-fee floor the cost
        # is constant, so spend the remaining budget in one closed-form step.
        if regime == "p2s_static" and bf <= BASE_FEE_FLOOR + 1e-12:
            return blocks + int(budget // cost)
        if cost > budget:
            break
        budget -= cost
        blocks += 1
        bf, bf_res = _advance_fees(regime, bf, bf_res)
    return blocks


def simulate_adaptive(budget_eth: float, reveal_fraction: float,
                      phi: float = PHI_REC, bf0: float = None,
                      max_blocks: int = 1_000_000) -> int:
    """Blocks a stuffer revealing fraction r of its dummy reservations sustains.

    Per-block cost  = reservation fee on the fully-reserved B1
                    + (base + tip) execution cost on the revealed r*G gas.
    Fee advancement: execution base fee sees r*G executed gas;
                     reservation base fee sees u = 1 - r unrevealed.
    """
    r = reveal_fraction
    if bf0 is None:
        bf0 = median_base_fee()
    bf, bf_res = bf0, bf0
    budget = budget_eth
    blocks = 0
    while blocks < max_blocks:
        cost = (phi * gas_eth(bf_res, GAS_LIMIT_BLOCK)
                + gas_eth(bf + PRIORITY_FEE_GWEI, int(r * GAS_LIMIT_BLOCK)))
        if cost > budget:
            break
        budget -= cost
        blocks += 1
        bf = next_base_fee(bf, r * GAS_LIMIT_BLOCK)
        bf_res = next_reservation_fee(bf_res, 1.0 - r)
    return blocks


def sweep_budgets(budgets_eth: List[float], phi: float = PHI_REC,
                  bf0: float = None) -> Dict[str, List[int]]:
    """{regime -> [blocks sustained per budget]} over a budget sweep.

    p2s_adaptive reports the WORST CASE (max duration) over the reveal-fraction
    grid at each budget: the best the evading stuffer can possibly do."""
    if bf0 is None:
        bf0 = median_base_fee()
    out = {
        regime: [simulate_duration(b, regime, phi=phi, bf0=bf0) for b in budgets_eth]
        for regime in REGIMES if regime != "p2s_adaptive"
    }
    out["p2s_adaptive"] = [
        max(simulate_adaptive(b, r, phi=phi, bf0=bf0) for r in ADAPTIVE_R_GRID)
        for b in budgets_eth
    ]
    return out


def base_fee_trajectory(n_blocks: int, phi: float = PHI_REC,
                        bf0: float = None):
    """Over a fixed horizon (no budget exhaustion), return the per-block pricing
    base fee and the per-block ETH cost for each regime, so the fee dynamics are
    isolated from budget effects.

    Returns (fee_gwei, cost_eth), each a {regime -> [value per block]} dict.
    Cost is the more informative series: Ethereum's execution base fee and the
    dynamic-phi reservation base fee escalate identically, but Ethereum pays the
    full execution gas while P2S pays only the phi fraction, so the three regimes
    separate cleanly in cost even where their base-fee trajectories coincide."""
    if bf0 is None:
        bf0 = median_base_fee()
    fee:  Dict[str, List[float]] = {}
    cost: Dict[str, List[float]] = {}
    r = ADAPTIVE_R_WORST
    for regime in REGIMES:
        bf, bf_res = bf0, bf0
        fee_series, cost_series = [], []
        for _ in range(n_blocks):
            # The fee that actually prices the attacker's per-block cost.
            fee_series.append(bf if regime in ("ethereum", "p2s_static") else bf_res)
            if regime == "p2s_adaptive":
                # Evader at the worst-case reveal fraction r: reservation fee on
                # the full B1 plus execution cost on the revealed r*G gas.
                cost_series.append(phi * gas_eth(bf_res, GAS_LIMIT_BLOCK)
                                   + gas_eth(bf + PRIORITY_FEE_GWEI,
                                             int(r * GAS_LIMIT_BLOCK)))
                bf = next_base_fee(bf, r * GAS_LIMIT_BLOCK)
                bf_res = next_reservation_fee(bf_res, 1.0 - r)
            else:
                cost_series.append(_per_block_cost(regime, bf, bf_res, phi))
                bf, bf_res = _advance_fees(regime, bf, bf_res)
        fee[regime], cost[regime] = fee_series, cost_series
    return fee, cost


def run(phi: float = PHI_REC, n_budgets: int = 25, traj_blocks: int = 60) -> dict:
    """Compute the full experiment payload (budgets, durations, trajectory)."""
    bf0 = median_base_fee()
    budgets = list(np.logspace(0, 3, n_budgets))   # 1 ETH .. 1000 ETH
    durations = sweep_budgets(budgets, phi=phi, bf0=bf0)
    fee_traj, cost_traj = base_fee_trajectory(traj_blocks, phi=phi, bf0=bf0)
    return {
        "phi": phi,
        "base_fee_start_gwei": bf0,
        "slot_seconds": SLOT_SECONDS,
        "budgets_eth": budgets,
        "blocks_sustained": durations,
        "seconds_sustained": {r: [b * SLOT_SECONDS for b in blks]
                              for r, blks in durations.items()},
        "trajectory_gwei": fee_traj,
        "cost_trajectory_eth": cost_traj,
    }


def main():
    os.makedirs(_DATA_DIR, exist_ok=True)
    payload = run()
    out = os.path.join(_DATA_DIR, "stuffing_duration.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)

    bf0 = payload["base_fee_start_gwei"]
    print(f"Starting base fee: {bf0:.2f} gwei, phi = {payload['phi']}")
    # Spot-check at a representative budget to confirm the result direction.
    budgets = payload["budgets_eth"]
    for b in (10.0, 100.0):
        i = min(range(len(budgets)), key=lambda j: abs(budgets[j] - b))
        line = "  ".join(
            f"{r}={payload['blocks_sustained'][r][i]}" for r in REGIMES
        )
        print(f"Budget {b:>6.0f} ETH  blocks:  {line}")
    print(f"Saved {out}")


if __name__ == "__main__":
    main()
