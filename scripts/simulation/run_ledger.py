#!/usr/bin/env python3
"""
P2S Block Ledger Runner — 100 blocks
Runs both P2S and Ethereum PoS simulations side-by-side and records, for
every block:
  • Block state (tx count, gas utilisation, MEV opportunity, packing metrics)
  • Per-block wallet *deltas*  (proposer earned, attacker net, users aggregate net)
  • Cumulative wallet *balances* after each block

Wallet roles
------------
  proposer    — the block validator that builds and proposes the block;
                earns the block reward (2 ETH issuance + priority-fee tips).
  attacker    — a single MEV attacker running the applicable strategy per protocol:
                  P2S         → blind insert (with optional no-reveal)
                  Ethereum PoS → whichever of front-run / sandwich / arbitrage
                                 yields the highest net gain that block.
  users       — aggregate of all transaction senders; they pay gas fees and
                suffer victim slippage (s_j ≈ m_j, but utility v_j−s_j−g_j > 0).

Money flow per block
--------------------
  users pay     gas_cost + victim_welfare_loss  (debit)
  proposer earns block_reward                   (credit; includes new ETH issuance)
  base fee      gas_cost - tip_revenue          (burned / destroyed — not tracked)
  P2S only      reservation_fees_burned         (also burned — F_res penalises g_limit over-declaration)
  attacker      gain_eth − cost_eth             (net; funded by victim slippage)
"""

import json
import os
import random
import sys
import time as _time_module

# ── disable simulation sleeps so 100 blocks run in seconds ──────────────────
_real_sleep = _time_module.sleep
_time_module.sleep = lambda _: None

# ── imports ──────────────────────────────────────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
sys.path.insert(0, _ROOT)
from scripts.simulation.simulator import (  # noqa: E402
    P2SSimulator,
    MEVAttackStrategies,
    ETH_MAINNET_BLOCK_GAS_LIMIT,
)

# ── constants ────────────────────────────────────────────────────────────────
NUM_BLOCKS = 1000
N_SEEDS    = 5
DATA_DIR   = os.path.join(_ROOT, "data")
OUTPUT_PATH = os.path.join(DATA_DIR, 'block_ledger_1000.json')

CONGESTION_LEVELS = [0.0, 0.1, 0.3, 0.5, 0.7]


# ─────────────────────────────────────────────────────────────────────────────
def run_ledger() -> None:
    sim = P2SSimulator()

    # ── load block data ──────────────────────────────────────────────────────
    ethereum_blocks = sim.load_ethereum_blocks(DATA_DIR)
    if not ethereum_blocks:
        print("❌  No Ethereum block cache found.")
        print("    Run: python scripts/extract_ethereum_blocks.py 1000 1")
        return

    while len(ethereum_blocks) < NUM_BLOCKS:
        ethereum_blocks.append(sim._synthetic_ethereum_block(len(ethereum_blocks)))
    ethereum_blocks = ethereum_blocks[:NUM_BLOCKS]
    print(f"✅  Using {NUM_BLOCKS} Ethereum blocks from cache.")

    # ── create validators (5 per protocol, round-robin) ─────────────────────
    NUM_VALIDATORS = 5
    for i in range(NUM_VALIDATORS):
        sim.create_validator(f"p2s_v{i}", "P2S")
        sim.create_validator(f"eth_v{i}", "Ethereum PoS")
    sim._p2s_proposer_index = 0
    sim._eth_proposer_index = 0

    # ── build block-level gas price list for attack strategies ───────────────
    block_gas_prices: list[float] = []
    for b in ethereum_blocks:
        txs = b.get('transactions', [])
        if txs:
            gp = txs[0].get('gasPrice', sim.base_gas_price_gwei * 1e9)
            if isinstance(gp, (int, float)) and gp > 1e9:
                gp = gp / 1e9
            block_gas_prices.append(float(gp) if gp > 0 else sim.base_gas_price_gwei)
        else:
            block_gas_prices.append(sim.base_gas_price_gwei)
    attack_strat = MEVAttackStrategies(block_gas_prices)

    # ── wallet state (cumulative ETH balances) ───────────────────────────────
    wallets: dict = {
        'p2s': {
            'proposers': {f"p2s_v{i}": 0.0 for i in range(NUM_VALIDATORS)},
            'attacker': 0.0,
            'users': 0.0,
        },
        'ethereum_pos': {
            'proposers': {f"eth_v{i}": 0.0 for i in range(NUM_VALIDATORS)},
            'attacker': 0.0,
            'users': 0.0,
        },
    }

    # ── main loop ────────────────────────────────────────────────────────────
    ledger: list[dict] = []

    for i, eth_block in enumerate(ethereum_blocks):
        congestion = random.choice(CONGESTION_LEVELS)

        # ── select proposers ─────────────────────────────────────────────────
        p2s_proposer = sim.select_proposer("P2S")
        eth_proposer = sim.select_proposer("Ethereum PoS")

        # ── simulate blocks ──────────────────────────────────────────────────
        p2s_blk = sim.simulate_p2s_block(i, p2s_proposer, eth_block, congestion)
        eth_blk = sim.simulate_ethereum_pos_block(i, eth_proposer, eth_block, congestion)

        # ── P2S attack: blind insert ─────────────────────────────────────────
        p2s_cost, p2s_gain, p2s_ok = attack_strat.run_blind_insert_p2s_no_reveal(i)
        # victim slippage: s_j ≈ m_j (α sampled from [0.90, 1.00])
        p2s_alpha = random.uniform(0.90, 1.00)
        p2s_victim_slippage = p2s_alpha * p2s_gain if p2s_ok else 0.0

        # ── Ethereum PoS attacks: run all three; record each; pick best ───────
        has_target = random.random() < 0.2
        fr_cost, fr_gain, fr_ok = attack_strat.run_front_run(i, has_target)
        sw_cost, sw_gain, sw_ok = attack_strat.run_sandwich(i, has_target)
        ab_cost, ab_gain, ab_ok = attack_strat.run_arbitrage(i)

        eth_all_attacks = {
            "front_run":  {"cost": fr_cost, "gain": fr_gain, "success": fr_ok},
            "sandwich":   {"cost": sw_cost, "gain": sw_gain, "success": sw_ok},
            "arbitrage":  {"cost": ab_cost, "gain": ab_gain, "success": ab_ok},
        }
        # rational attacker abstains when all strategies are net-negative (0 > loss)
        best_net  = max(v['gain'] - v['cost'] for v in eth_all_attacks.values())
        if best_net <= 0:
            best_name = "abort"
            eth_cost, eth_gain, eth_ok = 0.0, 0.0, False
        else:
            best_name = max(eth_all_attacks, key=lambda n: eth_all_attacks[n]['gain'] - eth_all_attacks[n]['cost'])
            best      = eth_all_attacks[best_name]
            eth_cost  = best['cost']
            eth_gain  = best['gain']
            eth_ok    = best['success']

        eth_alpha = random.uniform(0.90, 1.00) if best_name in ("front_run", "sandwich") else 0.0
        eth_victim_slippage = eth_alpha * eth_gain if eth_ok else 0.0

        # ── wallet deltas ────────────────────────────────────────────────────
        # P2S
        p2s_proposer_delta = p2s_blk['block_reward']
        p2s_attacker_delta = p2s_gain - p2s_cost
        # users pay all gas + victim slippage recorded from block-level estimate
        p2s_user_delta = -(p2s_blk['gas_cost'] + p2s_blk['victim_welfare_loss'])

        # Ethereum PoS
        eth_proposer_delta = eth_blk['block_reward']
        eth_attacker_delta = eth_gain - eth_cost
        eth_user_delta = -(eth_blk['gas_cost'] + eth_blk['victim_welfare_loss'])

        # ── update cumulative balances ────────────────────────────────────────
        wallets['p2s']['proposers'][p2s_proposer] += p2s_proposer_delta
        wallets['p2s']['attacker']                += p2s_attacker_delta
        wallets['p2s']['users']                   += p2s_user_delta

        wallets['ethereum_pos']['proposers'][eth_proposer] += eth_proposer_delta
        wallets['ethereum_pos']['attacker']                += eth_attacker_delta
        wallets['ethereum_pos']['users']                   += eth_user_delta

        # ── ledger entry ──────────────────────────────────────────────────────
        entry: dict = {
            "block_index": i,
            "ethereum_block_number": eth_block.get("block_number", i),
            "congestion_level": congestion,

            "p2s": {
                "block_state": {
                    "proposer_id":               p2s_proposer,
                    "tx_count":                  p2s_blk['transaction_count'],
                    "packing_gas_utilization":   round(p2s_blk.get('packing_gas_utilization', 0.0), 4),
                    "packing_fee_revenue_eth":   round(p2s_blk.get('packing_fee_revenue_eth', 0.0), 6),
                    "packing_excluded_txs":      p2s_blk.get('packing_excluded_txs', 0),
                    "block_reward_eth":          round(p2s_blk['block_reward'], 6),
                    "gas_cost_total_eth":        round(p2s_blk['gas_cost'], 6),
                    "reservation_fees_burned_eth": round(p2s_blk['reservation_fees_burned'], 6),
                    "mev_opportunity_eth":       round(p2s_blk['mev_opportunity'], 6),
                    "victim_welfare_loss_eth":   round(p2s_blk['victim_welfare_loss'], 6),
                    "block_total_time_s":        round(p2s_blk['total_time'], 4),
                    "network_latency_s":         round(p2s_blk['network_latency'], 4),
                },
                "attack": {
                    "strategy":         "blind_insert_p2s",
                    "has_mev_target":   False,
                    "cost_eth":         round(p2s_cost, 6),
                    "gain_eth":         round(p2s_gain, 6),
                    "net_eth":          round(p2s_gain - p2s_cost, 6),
                    "success":          p2s_ok,
                    "victim_slippage_eth": round(p2s_victim_slippage, 6),
                    # victim residual utility = v_j - s_j - g_j > 0
                    "victim_residual_utility_positive": True,
                },
                "wallet_deltas": {
                    "proposer_earned_eth":    round(p2s_proposer_delta, 6),
                    "attacker_net_eth":       round(p2s_attacker_delta, 6),
                    "users_aggregate_net_eth": round(p2s_user_delta, 6),
                },
                "wallet_state_after": {
                    "proposer_cumulative_eth": round(wallets['p2s']['proposers'][p2s_proposer], 6),
                    "all_proposers_total_eth": round(sum(wallets['p2s']['proposers'].values()), 6),
                    "attacker_cumulative_eth": round(wallets['p2s']['attacker'], 6),
                    "users_cumulative_eth":    round(wallets['p2s']['users'], 6),
                },
            },

            "ethereum_pos": {
                "block_state": {
                    "proposer_id":             eth_proposer,
                    "tx_count":                eth_blk['transaction_count'],
                    "packing_gas_utilization": round(eth_blk.get('packing_gas_utilization', 0.0), 4),
                    "packing_fee_revenue_eth": round(eth_blk.get('packing_fee_revenue_eth', 0.0), 6),
                    "packing_excluded_txs":    eth_blk.get('packing_excluded_txs', 0),
                    "block_reward_eth":        round(eth_blk['block_reward'], 6),
                    "gas_cost_total_eth":      round(eth_blk['gas_cost'], 6),
                    "mev_opportunity_eth":     round(eth_blk['mev_opportunity'], 6),
                    "victim_welfare_loss_eth": round(eth_blk['victim_welfare_loss'], 6),
                    "block_total_time_s":      round(eth_blk['total_time'], 4),
                    "network_latency_s":       round(eth_blk['network_latency'], 4),
                },
                "attack": {
                    "strategy":     best_name,
                    "has_mev_target": has_target,
                    "all_strategies": {
                        name: {
                            "cost_eth":  round(a['cost'], 6),
                            "gain_eth":  round(a['gain'], 6),
                            "net_eth":   round(a['gain'] - a['cost'], 6),
                            "success":   a['success'],
                        }
                        for name, a in eth_all_attacks.items()
                    },
                    "chosen_cost_eth":  round(eth_cost, 6),
                    "chosen_gain_eth":  round(eth_gain, 6),
                    "chosen_net_eth":   round(eth_gain - eth_cost, 6),
                    "success":          eth_ok,
                    "victim_slippage_eth": round(eth_victim_slippage, 6),
                    "victim_residual_utility_positive": True,
                },
                "wallet_deltas": {
                    "proposer_earned_eth":     round(eth_proposer_delta, 6),
                    "attacker_net_eth":        round(eth_attacker_delta, 6),
                    "users_aggregate_net_eth": round(eth_user_delta, 6),
                },
                "wallet_state_after": {
                    "proposer_cumulative_eth": round(wallets['ethereum_pos']['proposers'][eth_proposer], 6),
                    "all_proposers_total_eth": round(sum(wallets['ethereum_pos']['proposers'].values()), 6),
                    "attacker_cumulative_eth": round(wallets['ethereum_pos']['attacker'], 6),
                    "users_cumulative_eth":    round(wallets['ethereum_pos']['users'], 6),
                },
            },
        }

        ledger.append(entry)

        if (i + 1) % 100 == 0 or i == 0:
            p2s_att  = wallets['p2s']['attacker']
            eth_att  = wallets['ethereum_pos']['attacker']
            print(
                f"  Block {i+1:>4}/{NUM_BLOCKS}  "
                f"P2S attacker: {p2s_att:+.4f} ETH  "
                f"PoS attacker: {eth_att:+.4f} ETH"
            )

    # ── build final wallet summary ───────────────────────────────────────────
    final_wallets = {
        'p2s': {
            'proposers': {k: round(v, 6) for k, v in wallets['p2s']['proposers'].items()},
            'proposers_total_eth': round(sum(wallets['p2s']['proposers'].values()), 6),
            'attacker_eth': round(wallets['p2s']['attacker'], 6),
            'users_eth':    round(wallets['p2s']['users'], 6),
        },
        'ethereum_pos': {
            'proposers': {k: round(v, 6) for k, v in wallets['ethereum_pos']['proposers'].items()},
            'proposers_total_eth': round(sum(wallets['ethereum_pos']['proposers'].values()), 6),
            'attacker_eth': round(wallets['ethereum_pos']['attacker'], 6),
            'users_eth':    round(wallets['ethereum_pos']['users'], 6),
        },
    }

    output = {
        "metadata": {
            "num_blocks":          NUM_BLOCKS,
            "protocols":           ["P2S", "Ethereum PoS"],
            "packing_algorithm":   "Greedy-FD O(n log n) — matches Geth/Flashbots (Heimbach et al. arXiv:2411.03892)",
            "reservation_phi":     MEVAttackStrategies.PHT_RESERVATION_PHI,
            "victim_slippage_model": (
                "s_j ≈ m_j (α ∈ [0.90,1.00] for sandwich/front-run); "
                "victim utility v_j − s_j − g_j > 0 because v_j > s_j + g_j"
            ),
            "wallet_roles": {
                "proposer": "Block validator; earns 2 ETH issuance + priority-fee tips",
                "attacker": "MEV attacker; P2S→blind-insert, PoS→best of front-run/sandwich/arbitrage",
                "users":    "All tx senders aggregate; pay gas fees + victim slippage",
            },
        },
        "final_wallet_states": final_wallets,
        "blocks": ledger,
    }

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(OUTPUT_PATH, 'w') as f:
        json.dump(output, f, indent=2)

    print(f"\nLedger saved → {OUTPUT_PATH}")

    # ── print final summary ──────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print(f"FINAL WALLET BALANCES  (after {NUM_BLOCKS} blocks per protocol)")
    print("=" * 70)

    for proto_key, label in [('p2s', 'P2S'), ('ethereum_pos', 'Ethereum PoS')]:
        fw = final_wallets[proto_key]
        print(f"\n{label}:")
        for vid, bal in sorted(fw['proposers'].items()):
            print(f"  Proposer {vid:<12}: {bal:+.4f} ETH")
        print(f"  Proposers total  : {fw['proposers_total_eth']:+.4f} ETH")
        print(f"  Attacker         : {fw['attacker_eth']:+.4f} ETH")
        print(f"  Users (aggregate): {fw['users_eth']:+.4f} ETH")

    # ── attack success summary ───────────────────────────────────────────────
    p2s_successes = sum(1 for b in ledger if b['p2s']['attack']['success'])
    eth_successes = sum(1 for b in ledger if b['ethereum_pos']['attack']['success'])
    print(f"\nAttack successes over {NUM_BLOCKS} blocks:")
    print(f"  P2S  (blind insert)      : {p2s_successes}/{NUM_BLOCKS} ({p2s_successes}%)")
    print(f"  Ethereum PoS (best strat): {eth_successes}/{NUM_BLOCKS} ({eth_successes}%)")


def run_ledger_seed(seed: int) -> dict:
    """Run a single ledger simulation with the given random seed; return summary metrics."""
    random.seed(seed)

    sim = P2SSimulator()
    ethereum_blocks = sim.load_ethereum_blocks(DATA_DIR)
    while len(ethereum_blocks) < NUM_BLOCKS:
        ethereum_blocks.append(sim._synthetic_ethereum_block(len(ethereum_blocks)))
    ethereum_blocks = ethereum_blocks[:NUM_BLOCKS]

    NUM_VALIDATORS = 5
    for i in range(NUM_VALIDATORS):
        sim.create_validator(f"p2s_v{i}", "P2S")
        sim.create_validator(f"eth_v{i}", "Ethereum PoS")
    sim._p2s_proposer_index = 0
    sim._eth_proposer_index = 0

    block_gas_prices: list[float] = []
    for b in ethereum_blocks:
        txs = b.get("transactions", [])
        if txs:
            gp = txs[0].get("gasPrice", sim.base_gas_price_gwei * 1e9)
            if isinstance(gp, (int, float)) and gp > 1e9:
                gp = gp / 1e9
            block_gas_prices.append(float(gp) if gp > 0 else sim.base_gas_price_gwei)
        else:
            block_gas_prices.append(sim.base_gas_price_gwei)
    attack_strat = MEVAttackStrategies(block_gas_prices)

    p2s_mev_total = 0.0
    pos_mev_total = 0.0
    p2s_slip_total = 0.0
    pos_slip_total = 0.0
    p2s_success = 0
    pos_success = 0
    p2s_reward_total = 0.0
    pos_reward_total = 0.0

    for i, eth_block in enumerate(ethereum_blocks):
        congestion = random.choice(CONGESTION_LEVELS)
        p2s_proposer = sim.select_proposer("P2S")
        eth_proposer = sim.select_proposer("Ethereum PoS")

        p2s_blk = sim.simulate_p2s_block(i, p2s_proposer, eth_block, congestion)
        eth_blk = sim.simulate_ethereum_pos_block(i, eth_proposer, eth_block, congestion)

        p2s_cost, p2s_gain, p2s_ok = attack_strat.run_blind_insert_p2s_no_reveal(i)
        p2s_alpha = random.uniform(0.90, 1.00)
        p2s_victim_slippage = p2s_alpha * p2s_gain if p2s_ok else 0.0

        has_target = random.random() < 0.2
        fr_cost, fr_gain, fr_ok = attack_strat.run_front_run(i, has_target)
        sw_cost, sw_gain, sw_ok = attack_strat.run_sandwich(i, has_target)
        ab_cost, ab_gain, ab_ok = attack_strat.run_arbitrage(i)
        eth_all = {
            "front_run": (fr_cost, fr_gain, fr_ok),
            "sandwich":  (sw_cost, sw_gain, sw_ok),
            "arbitrage": (ab_cost, ab_gain, ab_ok),
        }
        best_net = max(g - c for c, g, _ in eth_all.values())
        if best_net <= 0:
            eth_cost, eth_gain, eth_ok = 0.0, 0.0, False
            best_name = "abort"
        else:
            best_name = max(eth_all, key=lambda n: eth_all[n][1] - eth_all[n][0])
            eth_cost, eth_gain, eth_ok = eth_all[best_name]
        eth_alpha = random.uniform(0.90, 1.00) if best_name in ("front_run", "sandwich") else 0.0
        eth_victim_slippage = eth_alpha * eth_gain if eth_ok else 0.0

        p2s_mev_total  += max(0.0, p2s_gain - p2s_cost)
        pos_mev_total  += max(0.0, eth_gain - eth_cost)
        p2s_slip_total += p2s_victim_slippage
        pos_slip_total += eth_victim_slippage
        p2s_success    += int(p2s_ok)
        pos_success    += int(eth_ok)
        p2s_reward_total += p2s_blk["block_reward"]
        pos_reward_total += eth_blk["block_reward"]

    return {
        "p2s_mev_eth":      p2s_mev_total,
        "pos_mev_eth":      pos_mev_total,
        "p2s_slip_eth":     p2s_slip_total,
        "pos_slip_eth":     pos_slip_total,
        "p2s_success_rate": p2s_success / NUM_BLOCKS,
        "pos_success_rate": pos_success / NUM_BLOCKS,
        "p2s_reward_eth":   p2s_reward_total,
        "pos_reward_eth":   pos_reward_total,
    }


def run_ledger_multi_seed(n_seeds: int = N_SEEDS, base_seed: int = 42) -> dict:
    """Run n_seeds independent ledger simulations; return mean ± std for each metric."""
    import numpy as np
    keys = ["p2s_mev_eth", "pos_mev_eth", "p2s_slip_eth", "pos_slip_eth",
            "p2s_success_rate", "pos_success_rate", "p2s_reward_eth", "pos_reward_eth"]
    rows = {k: [] for k in keys}

    for s in range(n_seeds):
        seed = base_seed + s * 10_000
        print(f"  Seed {seed} ({s+1}/{n_seeds}) …")
        r = run_ledger_seed(seed)
        for k in keys:
            rows[k].append(r[k])

    return {k: {"mean": float(np.mean(rows[k])), "std": float(np.std(rows[k], ddof=1))}
            for k in keys}


if __name__ == "__main__":
    print("=" * 70)
    print(f"P2S Block Ledger — {NUM_BLOCKS} Blocks")
    print("=" * 70)
    run_ledger()
