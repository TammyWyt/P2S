"""
Reveal-gap reservation fee: sustained-stuffing test with an ADAPTIVE stuffer.

Replaces the occupancy-keyed dynamic reservation base fee with one keyed on the
UNREVEALED-GAS FRACTION u_t (reserved gas whose MT never appears / total
reserved gas), with a benign no-show target u*:

    bf_res(t+1) = bf_res(t) * (1 + 0.125 * (u_t - u*) / (1 - u*))

Pure stuffer (u=1) escalates +12.5%/block exactly as the occupancy-keyed rule,
so the headline duration numbers are unchanged.  The new question this module
answers is EVASION: a stuffer that reveals a fraction r of its dummy
reservations to suppress u_t must execute that gas in B2, feeding the ordinary
EIP-1559 execution base fee.  With the execution target at half the limit, the
execution fee escalates for r > 0.5 while the reservation fee escalates for
r < 1 - u*; the regions overlap, so for every r at least one fee grows
geometrically and duration stays logarithmic in the budget.

Run:  python -m scripts.simulation.stuffing_reveal_gap
"""

import json
import os
from typing import Dict, List

import numpy as np

from .environment import median_base_fee
from .stuffing_duration import (
    PHI_REC, SLOT_SECONDS, U_TARGET,
    next_reservation_fee, simulate_adaptive,
)

_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data")


def run(phi: float = PHI_REC, n_budgets: int = 25) -> dict:
    """Duration vs budget for a grid of reveal fractions r."""
    bf0 = median_base_fee()
    budgets = list(np.logspace(0, 3, n_budgets))      # 1 .. 1000 ETH
    r_grid = [0.0, 0.25, 0.5, 0.6, 0.75, 0.9, 1.0]
    durations: Dict[str, List[int]] = {
        f"r={r:g}": [simulate_adaptive(b, r, phi=phi, bf0=bf0) for b in budgets]
        for r in r_grid
    }
    # Worst case over r at each budget: the best the adaptive stuffer can do.
    worst = [max(durations[f"r={r:g}"][i] for r in r_grid)
             for i in range(len(budgets))]
    return {
        "phi": phi,
        "u_target": U_TARGET,
        "base_fee_start_gwei": bf0,
        "slot_seconds": SLOT_SECONDS,
        "budgets_eth": budgets,
        "reveal_fractions": r_grid,
        "blocks_sustained": durations,
        "worst_case_blocks": worst,
    }


def main():
    os.makedirs(_DATA_DIR, exist_ok=True)
    payload = run()
    out = os.path.join(_DATA_DIR, "stuffing_reveal_gap.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)

    bf0 = payload["base_fee_start_gwei"]
    print(f"Starting base fee: {bf0:.2f} gwei, phi = {payload['phi']}, "
          f"u* = {payload['u_target']}")
    budgets = payload["budgets_eth"]
    print(f"\n{'budget (ETH)':>12} | " +
          " ".join(f"{k:>7}" for k in payload["blocks_sustained"]) +
          " | worst")
    for tag in (1.0, 10.0, 100.0, 1000.0):
        i = min(range(len(budgets)), key=lambda j: abs(budgets[j] - tag))
        row = " ".join(f"{payload['blocks_sustained'][k][i]:>7}"
                       for k in payload["blocks_sustained"])
        print(f"{budgets[i]:>12.1f} | {row} | {payload['worst_case_blocks'][i]:>5}")
    print(f"\nSaved {out}")


if __name__ == "__main__":
    main()
