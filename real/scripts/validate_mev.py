#!/usr/bin/env python3
"""Validation: the t8n-MEASURED sandwich profit must match an INDEPENDENT
closed-form Uniswap V2 computation (modulo attacker gas), and P2S must be a net
loss (so extractable MEV = 0). This is the MEV-sanity gate from the plan: it
confirms the real EVM execution reproduces the analytic AMM math, so the
headline figure is not an artifact of the harness.

Reads real/data/mev_sweep.json (measured) and recomputes analytic profit with
real/scripts/v2math.py. Passes if every measured PoS value sits just below its
analytic value by no more than the attacker's gas (a few 1e-4 ETH), and every
P2S value is <= 0.
"""
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from v2math import sandwich_profit
WEI = 10**18
GAS_TOL_ETH = 0.001  # attacker's 2-3 txs at ~1 gwei are well under this

def main():
    data = json.load(open(os.path.join(HERE, "..", "data", "mev_sweep.json")))
    pools = data["pools"]
    # reserves are needed in wei/token base units; reload the snapshot
    snap = json.load(open(os.path.join(HERE, "..", "data", "pool_reserves.json")))
    max_abs = 0.0
    max_rel = 0.0
    n_checked = 0
    p2s_violations = 0
    ok = True
    for name, p in pools.items():
        Re = snap["pools"][name]["reserve_eth_wei"]
        Rt = snap["pools"][name]["reserve_token"]
        for c in p["curve"]:
            F = int(round(c["front_run_eth"] * WEI))
            if F == 0:
                continue
            V = int(c["victim_eth"] * WEI)
            analytic_wei, _ = sandwich_profit(Re, Rt, F, V)
            analytic = analytic_wei / WEI
            measured = c["pos_mev_eth"]
            # measured = analytic - attacker_gas, so 0 <= analytic - measured <= gas_tol
            diff = analytic - measured
            abs_err = abs(diff)
            rel = abs_err / abs(analytic) if analytic else 0.0
            max_abs = max(max_abs, abs_err)
            max_rel = max(max_rel, rel)
            n_checked += 1
            if diff < -1e-9 or diff > GAS_TOL_ETH:
                ok = False
                print(f"  MISMATCH {name} V={c['victim_eth']}: analytic={analytic:.6f} "
                      f"measured={measured:.6f} diff={diff:.6f} ETH")
            # P2S must be a loss (extractable MEV = 0)
            if c["p2s_mev_eth"] > 1e-9:
                p2s_violations += 1
                ok = False
                print(f"  P2S>0 {name} V={c['victim_eth']}: {c['p2s_mev_eth']:.6f} ETH")

    print(f"checked {n_checked} profitable points across {len(pools)} pools")
    print(f"max |analytic - measured| = {max_abs*1000:.4f} mETH  (<= gas tol {GAS_TOL_ETH*1000:.1f} mETH)")
    print(f"max relative error        = {max_rel*100:.4f}%")
    print(f"P2S extractable MEV > 0 at any point: {p2s_violations} (must be 0)")
    print("VALIDATION:", "PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)

if __name__ == "__main__":
    main()
