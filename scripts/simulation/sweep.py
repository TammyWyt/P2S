"""
φ sweep runner: instantiates all agents, runs N blocks per φ value,
and returns per-agent activity rates and mean net profits with SE bands.
"""

import random
from typing import Dict, List, Tuple

import numpy as np

from .agents import ALL_AGENTS
from .constants import N_BLOCKS, PHI_SWEEP, RANDOM_SEED
from .environment import AMMPool, build_txpool, load_gas_prices


def _run_single(
    agents, phi_values, n_blocks, gas_prices, seed_offset, verbose,
):
    """One full φ sweep with a fixed seed offset. Returns (activity, net) dicts."""
    activity: Dict[str, List[float]] = {a.name: [] for a in agents}
    net:      Dict[str, List[float]] = {a.name: [] for a in agents}

    for phi_idx, phi in enumerate(phi_values):
        seed = RANDOM_SEED + seed_offset + phi_idx * 1000
        random.seed(seed)
        np.random.seed(seed)
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


def run_sweep(
    phi_values: List[float] = PHI_SWEEP,
    n_blocks:   int          = N_BLOCKS,
    gas_gwei:   float        = None,
    verbose:    bool         = True,
    n_reps:     int          = 3,
) -> Tuple[Dict[str, List[float]], Dict[str, List[float]],
           Dict[str, List[float]], Dict[str, List[float]]]:
    """
    Sweep φ values across n_reps independent random seeds.

    Gas prices are drawn block-by-block from the Ethereum block cache
    (base_fee + PRIORITY_FEE_GWEI per block), cycling through the 1005-block
    history as needed.  Pass gas_gwei to override with a fixed synthetic price.

    Returns:
        activity     — agent_name → [mean activity_rate per φ]
        net          — agent_name → [mean net_eth_per_block per φ]
        activity_se  — agent_name → [standard error of activity_rate per φ]
        net_se       — agent_name → [standard error of net_eth_per_block per φ]
    """
    agents     = [cls() for cls in ALL_AGENTS]
    gas_prices = [gas_gwei] * n_blocks if gas_gwei is not None else load_gas_prices(n_blocks)

    rep_activity = []
    rep_net      = []
    for rep in range(n_reps):
        if verbose:
            print(f"--- rep {rep + 1}/{n_reps} ---")
        act, nt = _run_single(
            agents, phi_values, n_blocks, gas_prices,
            seed_offset=rep * 100_000, verbose=verbose,
        )
        rep_activity.append(act)
        rep_net.append(nt)

    agent_names = [a.name for a in agents]
    n_phi       = len(phi_values)

    def _mean_se(reps, name):
        arr = np.array([reps[r][name] for r in range(n_reps)])  # (n_reps, n_phi)
        mean = arr.mean(axis=0).tolist()
        se   = (arr.std(axis=0, ddof=1) / np.sqrt(n_reps)).tolist() if n_reps > 1 else [0.0] * n_phi
        return mean, se

    activity:    Dict[str, List[float]] = {}
    net:         Dict[str, List[float]] = {}
    activity_se: Dict[str, List[float]] = {}
    net_se:      Dict[str, List[float]] = {}

    for name in agent_names:
        activity[name],    activity_se[name] = _mean_se(rep_activity, name)
        net[name],         net_se[name]      = _mean_se(rep_net,      name)

    return activity, net, activity_se, net_se
