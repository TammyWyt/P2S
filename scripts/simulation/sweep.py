"""
φ sweep runner: instantiates all agents, runs N blocks per φ value,
and returns per-agent activity rates and mean net profits.
"""

import random
from typing import Dict, List, Tuple

import numpy as np

from .agents import ALL_AGENTS
from .constants import N_BLOCKS, PHI_SWEEP, RANDOM_SEED
from .environment import AMMPool, build_txpool, load_gas_prices


def run_sweep(
    phi_values: List[float] = PHI_SWEEP,
    n_blocks:   int          = N_BLOCKS,
    verbose:    bool         = True,
) -> Tuple[Dict[str, List[float]], Dict[str, List[float]]]:
    """
    Sweep φ values, running n_blocks blocks per value with all agents.

    Gas prices are drawn block-by-block from the Ethereum block cache
    (base_fee + PRIORITY_FEE_GWEI per block), cycling through the 1005-block
    history as needed.  The activity_rate for each φ is therefore the fraction
    of historical blocks where the attack is profitable at that fee level.

    Returns:
        activity  — agent_name → [activity_rate per φ]
        net       — agent_name → [mean_net_eth_per_block per φ]
    """
    agents     = [cls() for cls in ALL_AGENTS]
    gas_prices = load_gas_prices(n_blocks)

    activity: Dict[str, List[float]] = {a.name: [] for a in agents}
    net:      Dict[str, List[float]] = {a.name: [] for a in agents}

    for phi_idx, phi in enumerate(phi_values):
        random.seed(RANDOM_SEED + phi_idx * 1000)
        np.random.seed(RANDOM_SEED + phi_idx * 1000)
        pool = AMMPool(1_000.0)

        for a in agents:
            a.reset()

        for i in range(n_blocks):
            gp     = gas_prices[i]
            txpool = build_txpool(random.randint(50, 200))
            for a in agents:
                a.step(phi, pool, txpool, gp)
            pool.step()

        for a in agents:
            activity[a.name].append(a.activity_rate)
            net[a.name].append(a.mean_net)

        if verbose:
            active = [a.name for a in agents if a.activity_rate > 0.005]
            print(f"  phi={phi:.4g}  active: {active or ['(none)']}")

    return activity, net
