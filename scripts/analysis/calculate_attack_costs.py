#!/usr/bin/env python3
"""
Calculate cost of attacks from simulation output.
Reads data/simulation_*.json and reports total cost, cost per attempt, and net (cost vs gain)
for Ethereum PoS and P2S attack strategies.
"""

import argparse
import glob
import json
import os
import sys


def load_simulation(path: str):
    """Load simulation JSON from path."""
    with open(path, "r") as f:
        return json.load(f)


def find_latest_simulation(data_dir: str):
    """Return path to most recent simulation_*.json in data_dir."""
    pattern = os.path.join(data_dir, "simulation_*.json")
    files = glob.glob(pattern)
    if not files:
        return None
    return max(files, key=os.path.getmtime)


def run_cost_report(sim: dict, eth_price_usd: float = 2000.0) -> dict:
    """
    Compute attack cost summary from simulation data.
    Returns a dict suitable for printing and saving.
    """
    report = {
        "source": "simulation",
        "num_blocks": sim.get("metadata", {}).get("num_blocks"),
        "eth_price_usd": eth_price_usd,
        "ethereum_pos": [],
        "p2s": [],
        "totals": {"ethereum_pos_cost_eth": 0.0, "p2s_cost_eth": 0.0},
    }

    # Ethereum PoS strategies
    for name, s in sim.get("attack_strategies", {}).items():
        total_cost = s["total_cost_eth"]
        cost_per = s["cost_per_attempt_eth"]
        attempts = s["attempts"]
        total_gain = s["total_gain_eth"]
        net = s["net_profit_eth"]
        report["ethereum_pos"].append({
            "strategy": name,
            "total_cost_eth": total_cost,
            "cost_per_attempt_eth": cost_per,
            "cost_per_success_eth": s.get("cost_per_success_eth"),
            "attempts": attempts,
            "total_gain_eth": total_gain,
            "net_profit_eth": net,
            "total_cost_usd": total_cost * eth_price_usd,
            "cost_per_attempt_usd": cost_per * eth_price_usd,
        })
        report["totals"]["ethereum_pos_cost_eth"] += total_cost

    # P2S strategies (only blind insert)
    for name, s in sim.get("attack_strategies_p2s", {}).items():
        total_cost = s["total_cost_eth"]
        cost_per = s["cost_per_attempt_eth"]
        attempts = s["attempts"]
        total_gain = s["total_gain_eth"]
        net = s["net_profit_eth"]
        report["p2s"].append({
            "strategy": name,
            "total_cost_eth": total_cost,
            "cost_per_attempt_eth": cost_per,
            "cost_per_success_eth": s.get("cost_per_success_eth"),
            "attempts": attempts,
            "total_gain_eth": total_gain,
            "net_profit_eth": net,
            "total_cost_usd": total_cost * eth_price_usd,
            "cost_per_attempt_usd": cost_per * eth_price_usd,
        })
        report["totals"]["p2s_cost_eth"] += total_cost

    return report


def print_report(report: dict) -> None:
    """Print cost of attacks to stdout."""
    n = report.get("num_blocks") or "?"
    eth_usd = report["eth_price_usd"]
    print("=" * 70)
    print("COST OF ATTACKS")
    print("=" * 70)
    print(f"Simulation blocks: {n}  |  ETH price (USD): {eth_usd}")
    print()

    if report["ethereum_pos"]:
        print("Ethereum PoS (per strategy)")
        print("-" * 70)
        for r in report["ethereum_pos"]:
            print(f"  {r['strategy']}")
            print(f"    Total cost:     {r['total_cost_eth']:.6f} ETH  ({r['total_cost_usd']:.2f} USD)")
            print(f"    Cost/attempt:   {r['cost_per_attempt_eth']:.6f} ETH  ({r['cost_per_attempt_usd']:.4f} USD)")
            if r.get("cost_per_success_eth") is not None:
                print(f"    Cost/success:   {r['cost_per_success_eth']:.6f} ETH  (high when success rate is low)")
            print(f"    Attempts:       {r['attempts']}  |  Gain: {r['total_gain_eth']:.6f} ETH  |  Net: {r['net_profit_eth']:.6f} ETH")
        print(f"  Total cost (all strategies): {report['totals']['ethereum_pos_cost_eth']:.6f} ETH")
        print()

    if report["p2s"]:
        print("P2S (blind insert only)")
        print("-" * 70)
        for r in report["p2s"]:
            print(f"  {r['strategy']}")
            print(f"    Total cost:     {r['total_cost_eth']:.6f} ETH  ({r['total_cost_usd']:.2f} USD)")
            print(f"    Cost/attempt:   {r['cost_per_attempt_eth']:.6f} ETH  ({r['cost_per_attempt_usd']:.4f} USD)")
            if r.get("cost_per_success_eth") is not None:
                print(f"    Cost/success:   {r['cost_per_success_eth']:.6f} ETH  (high when success rate is low)")
            print(f"    Attempts:       {r['attempts']}  |  Gain: {r['total_gain_eth']:.6f} ETH  |  Net: {r['net_profit_eth']:.6f} ETH")
        print(f"  Total cost (P2S): {report['totals']['p2s_cost_eth']:.6f} ETH")
    print("=" * 70)


def main():
    parser = argparse.ArgumentParser(description="Calculate cost of attacks from simulation data")
    parser.add_argument("--data-dir", default="data", help="Directory containing simulation_*.json")
    parser.add_argument("--file", "-f", help="Use this simulation file instead of latest")
    parser.add_argument("--eth-price", type=float, default=2000.0, help="ETH price in USD for report")
    parser.add_argument("--output", "-o", help="Write report JSON to this path")
    parser.add_argument("--quiet", "-q", action="store_true", help="Only write output file, no stdout")
    args = parser.parse_args()

    # Script lives in scripts/analysis/ → repo root is two levels up
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    data_dir = os.path.join(repo_root, args.data_dir)

    path = args.file
    if not path:
        path = find_latest_simulation(data_dir)
    else:
        if not os.path.isabs(path):
            path = os.path.join(repo_root, path)
    if not path or not os.path.isfile(path):
        print("No simulation file found. Run simulation first or pass --file.", file=sys.stderr)
        sys.exit(1)

    sim = load_simulation(path)
    report = run_cost_report(sim, eth_price_usd=args.eth_price)
    report["source_file"] = os.path.basename(path)

    if not args.quiet:
        print(f"Using: {report['source_file']}\n")
        print_report(report)

    if args.output:
        out_path = args.output if os.path.isabs(args.output) else os.path.join(repo_root, args.output)
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        with open(out_path, "w") as f:
            json.dump(report, f, indent=2)
        if not args.quiet:
            print(f"Report saved to {out_path}")


if __name__ == "__main__":
    main()
