"""Tail-sensitivity sweep for the MEV log-normal gain distribution.

Reviewer ask (C4): the heavy tail (sigma, cap) is anchored to the literature, not
fit, and drives every aggregate MEV figure. This script quantifies how the
qualitative conclusions move as the tail varies, and shows which are invariant.

For a grid of (sigma, cap) it runs the 1000-block agent simulation over several
seeds and records, with across-seed 95% CIs:
  - total content-dependent MEV removed by P2S (front-run + sandwich + atomic arb),
  - the analytic mean per-attack gain E[min(X, cap)], X ~ lognormal(mu, sigma),
  - the median per-attack gain exp(mu) (tail-INVARIANT by construction).

Run:  python3 scripts/tail_sensitivity.py
Out:  data/tail_sensitivity.json  (+ printed table)
"""
import os, sys, time, json, math, statistics
os.environ["MPLBACKEND"] = "Agg"
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)
os.chdir(_REPO)

import random
time.sleep = lambda *a, **k: None  # the per-block sleep only mimics latency wall-clock

from scripts.simulation import simulator as S

MU = math.log(0.00056)            # median anchor, held fixed (the measured quantity)
SIGMA_GRID = [2.5, 2.7, 2.85, 3.0, 3.2]
CAP_GRID = [25.0, 50.0, 100.0]
SEEDS = [42, 43, 44, 45, 46]
N_BLOCKS = 1000
ETH_USD = 3000.0
CONTENT_DEPENDENT = ("front_run", "sandwich", "arbitrage")  # P2S zeroes these


def analytic_mean_capped(mu, sigma, cap):
    """E[min(X, cap)] for X ~ lognormal(mu, sigma)."""
    from math import erf, sqrt, exp, log
    Phi = lambda z: 0.5 * (1 + erf(z / sqrt(2)))
    a = (log(cap) - mu - sigma**2) / sigma
    b = (log(cap) - mu) / sigma
    return exp(mu + sigma**2 / 2) * Phi(a) + cap * (1 - Phi(b))


def removed_eth_for(sigma, cap, seed):
    """One sim run; return total content-dependent MEV removed by P2S (ETH)."""
    S._MEV_SIG = sigma
    S._MEV_CAP = cap
    sim = S.P2SSimulator()       # __init__ seeds 42
    random.seed(seed)            # override for an independent replicate
    sim.run_simulation(N_BLOCKS)
    strat = sim.results.get("attack_strategies", {})
    return sum(float(strat.get(k, {}).get("total_gain_eth", 0.0)) for k in CONTENT_DEPENDENT)


def ci95(xs):
    if len(xs) < 2:
        return (xs[0] if xs else 0.0, 0.0)
    m = statistics.mean(xs)
    half = 1.96 * statistics.stdev(xs) / math.sqrt(len(xs))
    return m, half


def sweep(label, points):
    rows = []
    for sigma, cap in points:
        removed = [removed_eth_for(sigma, cap, s) for s in SEEDS]
        m, half = ci95(removed)
        rows.append({
            "sigma": sigma, "cap": cap,
            "removed_eth_mean": m, "removed_eth_ci95": half,
            "analytic_mean_gain_eth": analytic_mean_capped(MU, sigma, cap),
            "median_gain_eth": math.exp(MU),  # tail-invariant
        })
        print(f"[{label}] sigma={sigma:<4} cap={cap:<5} "
              f"removed={m:6.3f} +/- {half:5.3f} ETH | "
              f"mean_gain={rows[-1]['analytic_mean_gain_eth']*1000:6.3f} mETH "
              f"(${rows[-1]['analytic_mean_gain_eth']*ETH_USD:6.1f}) | "
              f"median_gain={rows[-1]['median_gain_eth']*1000:.3f} mETH (invariant)",
              flush=True)
    return rows


def main():
    print(">>> sigma sweep at cap=50")
    sigma_rows = sweep("sigma", [(s, 50.0) for s in SIGMA_GRID])
    print(">>> cap sweep at sigma=2.85")
    cap_rows = sweep("cap", [(2.85, c) for c in CAP_GRID])
    out = {
        "params": {"mu": MU, "median_gain_eth": math.exp(MU),
                   "n_blocks": N_BLOCKS, "seeds": SEEDS, "eth_usd": ETH_USD,
                   "content_dependent": list(CONTENT_DEPENDENT)},
        "sigma_sweep_cap50": sigma_rows,
        "cap_sweep_sigma2p85": cap_rows,
    }
    with open("data/tail_sensitivity.json", "w") as f:
        json.dump(out, f, indent=2)
    print("WROTE data/tail_sensitivity.json")


if __name__ == "__main__":
    main()
