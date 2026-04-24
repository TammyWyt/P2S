"""
φ sweep runner: instantiates all agents, runs N blocks per φ value,
and returns per-agent activity rates and mean net profits.
"""

import random
from typing import Dict, List, Tuple

import numpy as np

from .agents import ALL_AGENTS
from .constants import MEAN_GAS_GWEI, N_BLOCKS, PHI_SWEEP, RANDOM_SEED
from .environment import AMMPool, build_txpool


def run_sweep(
    phi_values: List[float] = PHI_SWEEP,
    n_blocks:   int          = N_BLOCKS,
    verbose:    bool         = True,
) -> Tuple[Dict[str, List[float]], Dict[str, List[float]]]:
    """
    Sweep φ values, running n_blocks blocks per value with all agents.

    Gas prices are fixed at the empirical mean (MEAN_GAS_GWEI) so that the
    simulated deactivation threshold aligns exactly with the analytical φ*
    (which is derived at mean gas price).

    Returns:
        activity  — agent_name → [activity_rate per φ]
        net       — agent_name → [mean_net_eth_per_block per φ]
    """
    agents   = [cls() for cls in ALL_AGENTS]
    gas_prices = [MEAN_GAS_GWEI] * n_blocks

    activity: Dict[str, List[float]] = {a.name: [] for a in agents}
    net:      Dict[str, List[float]] = {a.name: [] for a in agents}

    for phi_idx, phi in enumerate(phi_values):
        random.seed(RANDOM_SEED + phi_idx * 7)
        np.random.seed(RANDOM_SEED + phi_idx * 7)
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
            print(f"  phi={phi:.3f}  active: {active or ['(none)']}")

    return activity, net
