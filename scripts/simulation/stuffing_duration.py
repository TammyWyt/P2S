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

  p2s_dynamic — the proposed fix.  A reservation base fee bf_res keyed on the
                UTILIZATION GAP: the fraction u of B1 reserved gas that goes
                UNEXECUTED in B2 (no-shows count in full; revealed MTs count
                their unused remainder g_limit - g_used), against a benign
                under-utilization target u*, with slope MAX_CHANGE = 0.50
                (4x EIP-1559 — affordable because it binds only on the attack
                signature u > u*, never on benign congestion).  Merely revealing
                changes nothing — only executed gas lowers u.  A pure stuffer
                (u = 1) faces +50%/block, steeper than Ethereum's +12.5%; an
                evader that EXECUTES a fraction r of its reserved gas to
                suppress u = 1 - r feeds the ordinary execution base fee
                (escalates for r > 0.5) while the reservation fee escalates for
                r < 1 - u*; every r leaves at least one fee growing
                geometrically.  Durations are reported as the WORST CASE (max)
                over a grid of r — the best any stuffer, pure or evading, can
                do — and stay LOGARITHMIC in the budget.

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
REGIMES      = ("ethereum", "p2s_static", "p2s_dynamic")

# Utilization-gap reservation fee parameters.
U_TARGET   = 0.10          # benign under-utilization target u*
# Reservation-fee slope: 4x EIP-1559's 0.125.  Affordable because the term
# binds only when u > u* (the attack signature), which benign load never
# triggers; a pure stuffer faces +50%/block, steeper than Ethereum's +12.5%.
MAX_CHANGE = 0.50
ADAPTIVE_R_GRID  = (0.0, 0.25, 0.5, 0.6, 0.7, 0.75, 0.8, 0.85, 0.9, 1.0)
ADAPTIVE_R_WORST = 0.78    # large-budget optimum ~ crossing point r-dagger
# Fine grid used to locate the worst-case (longest-lasting) evading stuffer when
# sweeping the slope/phi: the optimal executed fraction shifts with the slope, so
# a coarse grid would understate the worst case.
R_GRID_FINE = tuple(i / 100.0 for i in range(101))

# ── Occupancy-keyed reservation fee (the alternative evaluated in
# sec:phi-experiments) ───────────────────────────────────────────────────────
# The utilization-gap fee above escalates only on the *unexecuted* fraction, so a
# stuffer evades it by executing most of its reserved gas (see sweep_slope).  The
# alternative keys escalation on B1 *reserved occupancy* above the gas target --
# the censorship signal itself -- which a stuffer cannot suppress by executing,
# since holding the chain requires reserving the whole block regardless.  The
# cost is that a content-agnostic protocol cannot tell an attacker's full block
# from a benign congested one, so this fee also escalates under honest
# congestion (quantified by benign_congestion_surcharge).
OCC_SLOPE = 0.50           # escalation slope on the reserved-occupancy gap


def next_reservation_fee(bf_res: float, u: float,
                         u_target: float = U_TARGET,
                         floor: float = BASE_FEE_FLOOR) -> float:
    """Utilization-gap update: escalate when the unexecuted fraction u of B1
    reserved gas exceeds u*.  Revealing without executing does not lower u."""
    delta = MAX_CHANGE * (u - u_target) / (1.0 - u_target)
    return max(floor, bf_res * (1.0 + delta))

def next_occupancy_fee(bf_res: float, reserved_fraction: float,
                       slope: float = OCC_SLOPE,
                       target_fraction: float = 0.5,
                       floor: float = BASE_FEE_FLOOR) -> float:
    """Occupancy-keyed update: escalate on B1 reserved gas above the gas target,
    regardless of how much of it executes.  ``reserved_fraction`` is the share of
    the block-gas-limit reserved in B1; ``target_fraction`` is the EIP-1559 target
    as a share of that limit (0.5).  A fully-reserved block (fraction 1.0) drives
    the fee up at the maximal ``slope`` whether or not the matching MTs execute,
    so the stuffer cannot suppress it by revealing."""
    delta = slope * (reserved_fraction - target_fraction) / target_fraction
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


def simulate_adaptive(budget_eth: float, executed_fraction: float,
                      phi: float = PHI_REC, bf0: float = None,
                      max_blocks: int = 1_000_000) -> int:
    """Blocks a stuffer executing fraction r of its reserved gas sustains.

    Per-block cost  = reservation fee on the fully-reserved B1
                    + (base + tip) execution cost on the executed r*G gas.
    Fee advancement: execution base fee sees r*G executed gas;
                     reservation base fee sees the utilization gap u = 1 - r.
    """
    r = executed_fraction
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


def simulate_occupancy(budget_eth: float, executed_fraction: float,
                       phi: float = PHI_REC, occ_slope: float = OCC_SLOPE,
                       bf0: float = None, max_blocks: int = 1_000_000) -> int:
    """Blocks a stuffer sustains under the occupancy-keyed reservation fee.

    Identical attacker model to ``simulate_adaptive`` (reserve the whole block,
    execute a fraction ``r``), but the reservation base fee escalates on the
    reserved occupancy (always the full block for a stuffer) rather than on the
    unexecuted gap, so executing more gas no longer suppresses it."""
    r = executed_fraction
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
        # Reserved occupancy is the full block regardless of r: censoring every
        # other transaction requires reserving the whole block.
        bf_res = next_occupancy_fee(bf_res, 1.0, slope=occ_slope)
    return blocks


def worst_case_duration(budget_eth: float, mechanism: str, phi: float = PHI_REC,
                        slope: float = None, bf0: float = None) -> int:
    """Longest duration any stuffing strategy achieves at ``budget_eth`` under a
    given reservation-fee ``mechanism`` ('gap' = utilization-gap, 'occupancy' =
    occupancy-keyed), maximised over the executed-fraction grid.  ``slope``
    overrides the mechanism's escalation slope (defaults to MAX_CHANGE / OCC_SLOPE)."""
    global MAX_CHANGE  # the gap update reads the module-level slope
    if bf0 is None:
        bf0 = median_base_fee()
    if mechanism == "gap":
        saved = MAX_CHANGE
        MAX_CHANGE = saved if slope is None else slope
        try:
            return max(simulate_adaptive(budget_eth, r, phi=phi, bf0=bf0)
                       for r in R_GRID_FINE)
        finally:
            MAX_CHANGE = saved
    if mechanism == "occupancy":
        s = OCC_SLOPE if slope is None else slope
        return max(simulate_occupancy(budget_eth, r, phi=phi, occ_slope=s, bf0=bf0)
                   for r in R_GRID_FINE)
    raise ValueError(f"unknown mechanism: {mechanism}")


def sweep_slope(budget_eth: float, slopes: List[float], phi: float = PHI_REC,
                bf0: float = None) -> Dict[str, List[int]]:
    """Worst-case stuffing duration vs escalation slope, for both reservation-fee
    mechanisms, at a fixed budget.  Shows that raising the *utilization-gap* slope
    cannot push the worst case below Ethereum (the evader retreats into the
    execution-fee regime where the reservation slope is irrelevant), whereas the
    occupancy-keyed fee does, because it cannot be evaded by executing."""
    if bf0 is None:
        bf0 = median_base_fee()
    eth = simulate_duration(budget_eth, "ethereum", phi=phi, bf0=bf0)
    return {
        "slopes": list(slopes),
        "ethereum": eth,
        "gap":       [worst_case_duration(budget_eth, "gap", phi=phi, slope=s, bf0=bf0)
                      for s in slopes],
        "occupancy": [worst_case_duration(budget_eth, "occupancy", phi=phi, slope=s, bf0=bf0)
                      for s in slopes],
    }


def sweep_phi(budget_eth: float, phis: List[float], bf0: float = None) -> Dict[str, List[int]]:
    """Worst-case utilization-gap duration vs the fee *level* phi, at a fixed
    budget and the default slope.  Like sweep_slope, demonstrates that raising the
    level cannot push the worst case below Ethereum either."""
    if bf0 is None:
        bf0 = median_base_fee()
    return {
        "phis": list(phis),
        "ethereum": simulate_duration(budget_eth, "ethereum", bf0=bf0),
        "gap": [worst_case_duration(budget_eth, "gap", phi=p, bf0=bf0) for p in phis],
    }


def benign_congestion_surcharge(n_blocks: int, g_limit: int = 150_000,
                                phi: float = PHI_REC, occ_slope: float = OCC_SLOPE,
                                bf0: float = None) -> Dict[str, List[float]]:
    """Reservation fee F_res (ETH) a benign user with declared gas ``g_limit``
    pays per block over a sustained *honest* congestion episode (full blocks whose
    reservations all execute), under each mechanism.

    Under the utilization-gap fee the benign user executes, so u <= u* and the
    reservation base fee never escalates -- F_res stays flat.  Under the
    occupancy-keyed fee the same full blocks escalate the reservation base fee,
    because a content-agnostic protocol cannot distinguish benign congestion from
    a stuffer's reserved occupancy -- so the honest user is taxed for congestion."""
    if bf0 is None:
        bf0 = median_base_fee()
    gap_fee, occ_fee = [], []
    bf_gap, bf_occ = bf0, bf0
    for _ in range(n_blocks):
        gap_fee.append(phi * gas_eth(bf_gap, g_limit))
        occ_fee.append(phi * gas_eth(bf_occ, g_limit))
        # Benign congestion: B1 is full and every reservation executes (u ~ 0).
        bf_gap = next_reservation_fee(bf_gap, 0.0)          # u below u* -> no rise
        bf_occ = next_occupancy_fee(bf_occ, 1.0, slope=occ_slope)  # full occupancy -> rises
    return {"gap": gap_fee, "occupancy": occ_fee, "g_limit": g_limit}


def sweep_budgets(budgets_eth: List[float], phi: float = PHI_REC,
                  bf0: float = None) -> Dict[str, List[int]]:
    """{regime -> [blocks sustained per budget]} over a budget sweep.

    p2s_dynamic reports the WORST CASE (max duration) over the executed-fraction
    grid at each budget — the best any stuffer, pure (r=0) or evading, can do."""
    if bf0 is None:
        bf0 = median_base_fee()
    out = {
        regime: [simulate_duration(b, regime, phi=phi, bf0=bf0) for b in budgets_eth]
        for regime in REGIMES if regime != "p2s_dynamic"
    }
    out["p2s_dynamic"] = [
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
            if regime == "p2s_dynamic":
                # The attacker's best strategy (executed fraction r ~ r-dagger):
                # reservation fee on the full B1 plus execution on the r*G gas.
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

    # Tuning sweeps at 1000 ETH: neither raising the utilization-gap slope nor
    # raising phi pushes the worst case below Ethereum; the occupancy-keyed fee
    # does.  Reported in sec:phi-experiments alongside the benign-cost tradeoff.
    ref_budget = 1000.0
    slope_grid = [0.125, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0]
    phi_grid   = [0.2, 0.4, 0.6, 1.0, 1.5, 2.0]
    slope_sweep   = sweep_slope(ref_budget, slope_grid, phi=phi, bf0=bf0)
    phi_sweep_st  = sweep_phi(ref_budget, phi_grid, bf0=bf0)
    surcharge     = benign_congestion_surcharge(traj_blocks, phi=phi, bf0=bf0)

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
        "tuning_ref_budget_eth": ref_budget,
        "slope_sweep": slope_sweep,
        "phi_sweep_static": phi_sweep_st,
        "benign_surcharge": surcharge,
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
