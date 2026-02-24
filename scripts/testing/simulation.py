#!/usr/bin/env python3
"""
P2S Simulation
Main simulation comparing P2S vs Ethereum PoS using real Ethereum block data.
Aligned with Ethereum mainnet: 1000 blocks, no stake (one node = one node),
gas fees and benign transactions from mainnet data. Includes multiple MEV
attack strategies with cost/gain evaluation.
"""

import json
import time
import random
import statistics
from datetime import datetime
from typing import List, Dict, Any, Tuple, Optional
from dataclasses import dataclass
import os
from collections import defaultdict
import glob

# Ethereum mainnet parameters (for alignment)
ETH_MAINNET_BLOCK_GAS_LIMIT = 30_000_000
ETH_MAINNET_BLOCK_TIME_SEC = 12
WEI_PER_ETH = 1e18
GWEI_PER_ETH = 1e9
DEFAULT_NUM_BLOCKS = 1000


@dataclass
class AttackStrategyResult:
    """Cost and gain for one attack strategy over the simulation."""
    name: str
    description: str
    total_cost_eth: float = 0.0
    total_gain_eth: float = 0.0
    attempts: int = 0
    successes: int = 0
    net_profit_eth: float = 0.0
    cost_per_attempt_eth: float = 0.0
    gain_per_success_eth: float = 0.0
    cost_per_success_eth: float = 0.0  # total_cost / successes; high when success rate is low


class MEVAttackStrategies:
    """
    Simulate MEV attack strategies and evaluate cost vs gain.

    In P2S, B1 contains only PHTs (commitments). You cannot target a specific tx for
    front-run/sandwich — those strategies are NOT applicable in P2S. The only
    applicable strategy is blind insert, with optional no-reveal after B1:

    - Attacker submits a PHT (blind attack) without knowing other txs' content.
    - After B1 is confirmed, they see revealed content (e.g. when building B2 or
      when MTs are revealed) and can tell if their attack would be profitable.
    - If not the right attack: they choose NOT to reveal → tx is not processed,
      but they still pay the gas fee (one gas fee for PHT inclusion in B1).
    - Protocol note: This can work as a single gas-fee transaction if the
      protocol charges gas at B1 for PHT inclusion; then no-reveal still pays
      that one fee. If gas were only charged at B2 on reveal, the protocol would
      need another mechanism (e.g. commitment fee at B1) to ensure cost on no-reveal.
    """
    GAS_BLIND_INSERT = 150_000
    GAS_FRONT_RUN = 200_000
    GAS_SANDWICH_FRONT = 200_000
    GAS_SANDWICH_BACK = 150_000
    GAS_ARBITRAGE = 300_000

    def __init__(self, block_gas_prices_gwei: List[float]):
        self.block_gas_prices = block_gas_prices_gwei

    @staticmethod
    def gas_cost_eth(gas_price_gwei: float, gas_units: int) -> float:
        """Ethereum mainnet gas cost in ETH: (gas_price_wei * gas_used) / 1e18."""
        return (gas_price_gwei * GWEI_PER_ETH * gas_units) / WEI_PER_ETH

    def run_blind_insert(self, block_idx: int) -> Tuple[float, float, bool]:
        """Blindly insert attack tx without mempool visibility. Returns (cost_eth, gain_eth, success)."""
        gas_price = self.block_gas_prices[block_idx % len(self.block_gas_prices)]
        cost = self.gas_cost_eth(gas_price, self.GAS_BLIND_INSERT)
        success = random.random() < 0.05
        gain = (random.uniform(0.01, 0.5) if success else 0.0)
        return (cost, gain, success)

    def run_blind_insert_p2s_no_reveal(self, block_idx: int) -> Tuple[float, float, bool]:
        """
        P2S-only: Blind insert with optional no-reveal after B1.
        Cost: one gas fee per attempt (PHT inclusion in B1), paid whether or not
        the attacker reveals in B2. If they don't reveal (attack doesn't fit),
        tx is not processed but gas is still paid (single gas-fee transaction).
        Gain: only when they reveal and the attack succeeds.
        """
        gas_price = self.block_gas_prices[block_idx % len(self.block_gas_prices)]
        cost = self.gas_cost_eth(gas_price, self.GAS_BLIND_INSERT)  # always pay for PHT inclusion
        # After B1, attacker sees whether their attack fits; if not, they don't reveal (gain=0)
        attack_fits = random.random() < 0.15  # probability blind attack matches opportunity
        if not attack_fits:
            return (cost, 0.0, False)  # don't reveal → not processed, still paid gas
        success = random.random() < 0.4  # given fit, probability reveal and succeed
        gain = (random.uniform(0.01, 0.5) if success else 0.0)
        return (cost, gain, success)

    def run_front_run(self, block_idx: int, block_has_mev_target: bool) -> Tuple[float, float, bool]:
        """Requires seeing target tx (Ethereum mempool). In P2S B1=PHT only → no target."""
        gas_price = self.block_gas_prices[block_idx % len(self.block_gas_prices)]
        cost = self.gas_cost_eth(gas_price * 1.2, self.GAS_FRONT_RUN)
        if not block_has_mev_target:
            return (cost, 0.0, False)
        success = random.random() < 0.7
        gain = (random.uniform(0.05, 0.8) if success else 0.0)
        return (cost, gain, success)

    def run_sandwich(self, block_idx: int, block_has_mev_target: bool) -> Tuple[float, float, bool]:
        """Requires seeing target tx (Ethereum mempool). In P2S B1=PHT only → no target."""
        gas_price = self.block_gas_prices[block_idx % len(self.block_gas_prices)]
        cost = self.gas_cost_eth(gas_price * 1.3, self.GAS_SANDWICH_FRONT) + \
               self.gas_cost_eth(gas_price * 1.1, self.GAS_SANDWICH_BACK)
        if not block_has_mev_target:
            return (cost, 0.0, False)
        success = random.random() < 0.5
        gain = (random.uniform(0.02, 1.0) if success else 0.0)
        return (cost, gain, success)

    def run_arbitrage(self, block_idx: int) -> Tuple[float, float, bool]:
        gas_price = self.block_gas_prices[block_idx % len(self.block_gas_prices)]
        cost = self.gas_cost_eth(gas_price, self.GAS_ARBITRAGE)
        success = random.random() < 0.09  # ~15% opportunity * 60% success
        gain = (random.uniform(0.01, 0.4) if success else 0.0)
        return (cost, gain, success)

    def evaluate_all_strategies(
        self,
        num_blocks: int,
        block_has_mev_target_fn: Optional[Any] = None,
        target_visibility: bool = True,
    ) -> Dict[str, AttackStrategyResult]:
        """
        Evaluate cost and gain for each strategy.
        target_visibility=False (P2S): B1 has only PHTs → front_run/sandwich have no target, gain=0.
        target_visibility=True (Ethereum PoS): mempool visible → targets can exist.
        """
        if target_visibility and block_has_mev_target_fn is None:
            def default_has_target(_i: int) -> bool:
                return random.random() < 0.2
            has_target = default_has_target
        elif not target_visibility:
            has_target = lambda _i: False  # P2S: cannot target from B1
        else:
            has_target = block_has_mev_target_fn

        results = {}
        # Ethereum PoS: only targeted strategies (front_run, sandwich, arbitrage).
        # Blind insert is NOT rational on Ethereum — mempool is visible, so you target instead.
        for name, desc, run_fn in [
            ("front_run", "Front-run visible target tx",
             lambda i: self.run_front_run(i, has_target(i))),
            ("sandwich", "Sandwich attack (front + back run)",
             lambda i: self.run_sandwich(i, has_target(i))),
            ("arbitrage", "Cross-DEX arbitrage",
             lambda i: self.run_arbitrage(i)),
        ]:
            total_cost = 0.0
            total_gain = 0.0
            attempts = num_blocks
            successes = 0
            for i in range(num_blocks):
                cost, gain, success = run_fn(i)
                total_cost += cost
                total_gain += gain
                if success:
                    successes += 1
            net = total_gain - total_cost
            cost_per_success = total_cost / successes if successes > 0 else total_cost
            results[name] = AttackStrategyResult(
                name=name,
                description=desc,
                total_cost_eth=total_cost,
                total_gain_eth=total_gain,
                attempts=attempts,
                successes=successes,
                net_profit_eth=net,
                cost_per_attempt_eth=total_cost / attempts if attempts else 0,
                gain_per_success_eth=total_gain / successes if successes else 0,
                cost_per_success_eth=cost_per_success,
            )
        return results

    def evaluate_p2s_strategies(self, num_blocks: int) -> Dict[str, AttackStrategyResult]:
        """
        P2S only: the only applicable strategy is blind insert (with no-reveal after B1).
        Front-run, sandwich, arbitrage are NOT applicable — you cannot
        target from B1 (PHT only). Results contain only 'blind_insert_p2s'.
        """
        total_cost = 0.0
        total_gain = 0.0
        successes = 0
        for i in range(num_blocks):
            cost, gain, success = self.run_blind_insert_p2s_no_reveal(i)
            total_cost += cost
            total_gain += gain
            if success:
                successes += 1
        net = total_gain - total_cost
        cost_per_success = total_cost / successes if successes > 0 else total_cost
        return {
            "blind_insert_p2s": AttackStrategyResult(
                name="blind_insert_p2s",
                description="Blind insert; after B1 can choose not to reveal (tx not processed, gas still paid)",
                total_cost_eth=total_cost,
                total_gain_eth=total_gain,
                attempts=num_blocks,
                successes=successes,
                net_profit_eth=net,
                cost_per_attempt_eth=total_cost / num_blocks if num_blocks else 0,
                gain_per_success_eth=total_gain / successes if successes else 0,
                cost_per_success_eth=cost_per_success,
            )
        }


class P2SSimulator:
    """Simulator: 1000 blocks, no stake (one node = one node), Ethereum mainnet gas and benign tx."""

    def __init__(self):
        self.network_latency_base = 0.1
        self.network_jitter = 0.05
        self.base_gas_price_gwei = 20  # fallback gwei (Ethereum mainnet typical range)

        self.results = {
            'p2s_data': [],
            'ethereum_pos_data': [],
            'profit_distribution': {'p2s': {}, 'ethereum_pos': {}},
            'mev_reordering': {'p2s': [], 'ethereum_pos': []},
            'overhead_metrics': {'p2s': {}, 'ethereum_pos': {}},
            'attack_strategies': {},
            'metadata': {
                'timestamp': datetime.now().strftime("%Y%m%d_%H%M%S"),
                'description': "P2S simulation: 1000 blocks, no stake, Ethereum mainnet gas, MEV attack strategies",
                'num_blocks': DEFAULT_NUM_BLOCKS,
                'ethereum_mainnet_alignment': {
                    'block_gas_limit': ETH_MAINNET_BLOCK_GAS_LIMIT,
                    'block_time_sec': ETH_MAINNET_BLOCK_TIME_SEC,
                }
            }
        }
        self.validators = {}
        self.transactions = {}
        self.block_rewards = defaultdict(float)
        self._p2s_proposer_index = 0
        self._eth_proposer_index = 0
        
    def load_ethereum_blocks(self, data_dir="data") -> List[Dict]:
        """Load real Ethereum block data from cache"""
        cache_file = f"{data_dir}/ethereum_blocks_cache.json"
        
        if not os.path.exists(cache_file):
            print("⚠️  No Ethereum block data found. Run extract_ethereum_blocks.py first.")
            return []
        
        print(f"📂 Loading Ethereum blocks from cache: {cache_file}")
        
        with open(cache_file, 'r') as f:
            cached_data = json.load(f)
            # Cache is a dict of block_number -> block_data
            blocks = list(cached_data.values())
            print(f"✅ Loaded {len(blocks)} blocks from cache")
            return blocks

    def _synthetic_ethereum_block(self, block_number: int) -> Dict:
        """Generate a synthetic Ethereum-style block when cache has fewer than num_blocks."""
        tx_count = random.randint(50, 200)
        transactions = []
        for i in range(tx_count):
            transactions.append({
                'hash': f"0x{random.getrandbits(256):064x}",
                'from': f"0x{random.getrandbits(160):040x}",
                'to': f"0x{random.getrandbits(160):040x}",
                'value': random.randint(10**15, 10**19),
                'gas': random.randint(21000, 500000),
                'gasPrice': random.randint(20 * 10**9, 100 * 10**9),
                'nonce': i,
            })
        return {
            'block_number': block_number,
            'timestamp': int(time.time()),
            'transaction_count': tx_count,
            'transactions': transactions,
        }

    def create_validator(self, validator_id: str, protocol: str):
        """Create a validator (one node = one node; no stake used for selection)."""
        self.validators[validator_id] = {
            'id': validator_id,
            'protocol': protocol,
            'blocks_proposed': 0,
            'total_rewards': 0.0,
            'total_gas_costs': 0.0,
            'net_profit': 0.0,
            'mev_extracted': 0.0
        }
    
    def gas_cost_eth(self, gas_price_gwei: float, gas_units: int) -> float:
        """Ethereum mainnet: cost in ETH = (gas_price_wei * gas_used) / 1e18."""
        return (gas_price_gwei * GWEI_PER_ETH * gas_units) / WEI_PER_ETH

    def simulate_network_delay(self, congestion_level=0.0):
        """Simulate network delay"""
        base_delay = self.network_latency_base
        jitter = random.uniform(-self.network_jitter, self.network_jitter)
        congestion_delay = congestion_level * random.uniform(0.5, 2.0)
        return max(0.01, base_delay + jitter + congestion_delay)
    
    def calculate_reordering_opportunity(self, transactions: List[Dict]) -> float:
        """Calculate MEV opportunity from transaction reordering"""
        if len(transactions) < 2:
            return 0.0
        
        # Calculate potential MEV from reordering
        # Higher value transactions with lower gas prices = reordering opportunity
        mev_opportunity = 0.0
        for tx in transactions:
            # Convert gasPrice from wei to gwei if needed; support both raw and converted tx format
            gas_price = tx.get('gas_price') or tx.get('gasPrice', 0)
            if gas_price > 1e15:  # Likely in wei, convert to gwei
                gas_price = gas_price / 1e9
            value = tx.get('value', 0)
            if isinstance(value, str):
                try:
                    value = int(value, 16) if value.startswith('0x') else int(value)
                except Exception:
                    value = 0

            # If high value but low gas price, there's reordering potential
            if value > 1e18 and gas_price < 50:  # > 1 ETH value, < 50 gwei
                mev_opportunity += (value / 1e18) * 0.05  # 5% of value in ETH as potential MEV

        return mev_opportunity
    
    def convert_ethereum_tx(self, eth_tx: Dict) -> Dict:
        """Convert Ethereum transaction format to our format"""
        gas_price = eth_tx.get('gasPrice', 0)
        if isinstance(gas_price, str):
            gas_price = int(gas_price, 16) if gas_price.startswith('0x') else int(gas_price)
        
        value = eth_tx.get('value', 0)
        if isinstance(value, str):
            value = int(value, 16) if value.startswith('0x') else int(value)
        
        return {
            'hash': eth_tx.get('hash', ''),
            'value': value,
            'gas_price': gas_price / 1e9 if gas_price > 1e9 else gas_price,  # Convert to gwei
            'gas_limit': eth_tx.get('gas', 21000),
            'from': eth_tx.get('from', ''),
            'to': eth_tx.get('to', ''),
            'complexity': random.uniform(0.5, 2.0)
        }
    
    def simulate_p2s_block(self, block_num: int, proposer_id: str, ethereum_block: Dict, congestion: float):
        """Simulate P2S block processing using real Ethereum block data"""
        start_time = time.time()
        
        # Convert Ethereum transactions
        transactions = [self.convert_ethereum_tx(tx) for tx in ethereum_block.get('transactions', [])]
        
        # Phase 1: PHT Creation
        pht_time = sum(random.uniform(0.01, 0.05) * tx.get('complexity', 1.0) for tx in transactions)
        time.sleep(min(pht_time, 0.1))  # Cap at 0.1s for simulation speed
        
        # Phase 2: B1 Block
        b1_time = self.simulate_network_delay(congestion) + random.uniform(0.05, 0.15)
        time.sleep(min(b1_time, 0.2))
        
        # Phase 3: MT Creation
        mt_time = sum(random.uniform(0.02, 0.08) * tx.get('complexity', 1.0) for tx in transactions)
        time.sleep(min(mt_time, 0.1))
        
        # Phase 4: B2 Block
        b2_time = self.simulate_network_delay(congestion) + random.uniform(0.05, 0.15)
        time.sleep(min(b2_time, 0.2))
        
        total_time = time.time() - start_time

        # Ethereum mainnet gas cost: (gas_price_gwei * 1e9 * gas_limit) / 1e18 ETH per tx
        gas_cost = sum(
            self.gas_cost_eth(tx.get('gas_price', self.base_gas_price_gwei), tx.get('gas_limit', 21000))
            for tx in transactions
        )
        # Block reward: fixed issuance + fraction of tx fees (benign, mainnet-like)
        block_reward = 2.0 + sum(
            self.gas_cost_eth(tx.get('gas_price', self.base_gas_price_gwei), tx.get('gas_limit', 21000)) * 0.1
            for tx in transactions
        )

        # MEV reordering opportunity (reduced in P2S due to hidden details)
        mev_opportunity = self.calculate_reordering_opportunity(transactions) * 0.1

        # Update validator metrics
        if proposer_id in self.validators:
            self.validators[proposer_id]['blocks_proposed'] += 1
            self.validators[proposer_id]['total_rewards'] += block_reward
            self.validators[proposer_id]['total_gas_costs'] += gas_cost
            self.validators[proposer_id]['net_profit'] = (
                self.validators[proposer_id]['total_rewards'] -
                self.validators[proposer_id]['total_gas_costs']
            )

        return {
            'block_number': ethereum_block.get('block_number', block_num),
            'proposer': proposer_id,
            'protocol': 'P2S',
            'transaction_count': len(transactions),
            'total_time': total_time,
            'pht_time': pht_time,
            'b1_time': b1_time,
            'mt_time': mt_time,
            'b2_time': b2_time,
            'gas_cost': gas_cost,
            'block_reward': block_reward,
            'mev_opportunity': mev_opportunity,
            'network_latency': b1_time + b2_time,
            'congestion_level': congestion
        }
    
    def simulate_ethereum_pos_block(self, block_num: int, proposer_id: str, ethereum_block: Dict, congestion: float):
        """Simulate standard Ethereum PoS block using real Ethereum data"""
        start_time = time.time()
        
        # Convert Ethereum transactions
        transactions = [self.convert_ethereum_tx(tx) for tx in ethereum_block.get('transactions', [])]
        
        # Mempool processing
        mempool_time = random.uniform(0.01, 0.05) * len(transactions) / 100
        time.sleep(min(mempool_time, 0.05))
        
        # Block proposal (validator can see all transaction details and reorder)
        proposal_time = self.simulate_network_delay(congestion) + random.uniform(0.05, 0.15)
        time.sleep(min(proposal_time, 0.2))
        
        # Confirmation
        confirmation_time = self.simulate_network_delay(congestion)
        time.sleep(min(confirmation_time, 0.1))
        
        total_time = time.time() - start_time

        # Ethereum mainnet gas cost per tx
        gas_cost = sum(
            self.gas_cost_eth(tx.get('gas_price', self.base_gas_price_gwei), tx.get('gas_limit', 21000))
            for tx in transactions
        )
        block_reward = 2.0 + sum(
            self.gas_cost_eth(tx.get('gas_price', self.base_gas_price_gwei), tx.get('gas_limit', 21000)) * 0.1
            for tx in transactions
        )

        # MEV reordering (full visibility in PoS)
        mev_opportunity = self.calculate_reordering_opportunity(transactions) * 1.0

        if proposer_id in self.validators:
            self.validators[proposer_id]['blocks_proposed'] += 1
            self.validators[proposer_id]['total_rewards'] += block_reward
            self.validators[proposer_id]['total_gas_costs'] += gas_cost
            self.validators[proposer_id]['net_profit'] = (
                self.validators[proposer_id]['total_rewards'] -
                self.validators[proposer_id]['total_gas_costs']
            )
            self.validators[proposer_id]['mev_extracted'] += mev_opportunity * 0.6

        return {
            'block_number': ethereum_block.get('block_number', block_num),
            'proposer': proposer_id,
            'protocol': 'Ethereum PoS',
            'transaction_count': len(transactions),
            'total_time': total_time,
            'mempool_time': mempool_time,
            'proposal_time': proposal_time,
            'confirmation_time': confirmation_time,
            'gas_cost': gas_cost,
            'block_reward': block_reward,
            'mev_opportunity': mev_opportunity,
            'network_latency': proposal_time + confirmation_time,
            'congestion_level': congestion
        }
    
    def calculate_gini_coefficient(self, values: List[float]) -> float:
        """Calculate Gini coefficient for profit distribution"""
        if not values or all(v == 0 for v in values):
            return 0.0
        
        sorted_values = sorted(values)
        n = len(sorted_values)
        cumsum = 0
        for i, value in enumerate(sorted_values, 1):
            cumsum += value * (2 * i - n - 1)
        
        return cumsum / (n * sum(sorted_values)) if sum(sorted_values) > 0 else 0.0
    
    def run_simulation(self, num_blocks: int = DEFAULT_NUM_BLOCKS):
        """Run simulation: exactly num_blocks (default 1000), no stake, Ethereum mainnet gas, benign tx + attack strategies."""
        print("=" * 80)
        print("P2S SIMULATION (Ethereum mainnet aligned)")
        print("=" * 80)
        print(f"Simulating {num_blocks} blocks per protocol")
        print("No stake: one node = one node (equal proposer rotation)")
        print("Gas fees and benign tx from Ethereum mainnet data")
        print("=" * 80)

        ethereum_blocks = self.load_ethereum_blocks()
        if not ethereum_blocks:
            print("❌ No Ethereum block data. Run: python scripts/extract_ethereum_blocks.py 1000 1")
            return None

        # Use exactly num_blocks (pad with synthetic if cache has fewer)
        if len(ethereum_blocks) < num_blocks:
            print(f"⚠️  Cache has {len(ethereum_blocks)} blocks; padding to {num_blocks} with synthetic blocks")
            for i in range(len(ethereum_blocks), num_blocks):
                ethereum_blocks.append(self._synthetic_ethereum_block(i))
        ethereum_blocks = ethereum_blocks[:num_blocks]

        # Create validators: no stake, equal nodes
        num_validators = 10
        for i in range(num_validators):
            self.create_validator(f"p2s_validator_{i}", "P2S")
            self.create_validator(f"ethereum_pos_validator_{i}", "Ethereum PoS")

        self._p2s_proposer_index = 0
        self._eth_proposer_index = 0
        congestion_levels = [0.0, 0.1, 0.3, 0.5, 0.7]

        for i, ethereum_block in enumerate(ethereum_blocks):
            congestion = random.choice(congestion_levels)
            p2s_proposer = self.select_proposer("P2S")
            ethereum_pos_proposer = self.select_proposer("Ethereum PoS")
            p2s_block = self.simulate_p2s_block(i, p2s_proposer, ethereum_block, congestion)
            ethereum_pos_block = self.simulate_ethereum_pos_block(i, ethereum_pos_proposer, ethereum_block, congestion)
            self.results['p2s_data'].append(p2s_block)
            self.results['ethereum_pos_data'].append(ethereum_pos_block)
            if (i + 1) % 100 == 0 or (i + 1) == len(ethereum_blocks):
                print(f"Processed {i + 1}/{len(ethereum_blocks)} blocks...")

        # Attack strategy cost/gain evaluation (using block gas prices from benign tx)
        block_gas_prices = []
        for b in ethereum_blocks:
            txs = b.get('transactions', [])
            if txs:
                gp = txs[0].get('gasPrice', self.base_gas_price_gwei * GWEI_PER_ETH)
                if isinstance(gp, int) and gp > 1e9:
                    gp = gp / 1e9
                block_gas_prices.append(float(gp) if gp > 0 else self.base_gas_price_gwei)
            else:
                block_gas_prices.append(self.base_gas_price_gwei)
        attack_eval = MEVAttackStrategies(block_gas_prices)
        # Ethereum PoS: full mempool visibility → all strategies (front_run, sandwich, etc.) apply
        strategy_results = attack_eval.evaluate_all_strategies(num_blocks, target_visibility=True)
        self.results['attack_strategies'] = {
            name: {
                'description': r.description,
                'total_cost_eth': r.total_cost_eth,
                'total_gain_eth': r.total_gain_eth,
                'attempts': r.attempts,
                'successes': r.successes,
                'net_profit_eth': r.net_profit_eth,
                'cost_per_attempt_eth': r.cost_per_attempt_eth,
                'gain_per_success_eth': r.gain_per_success_eth,
                'cost_per_success_eth': r.cost_per_success_eth,
            }
            for name, r in strategy_results.items()
        }
        # P2S: B1 = PHT only → cannot target → only blind insert (with no-reveal) is applicable
        strategy_results_p2s = attack_eval.evaluate_p2s_strategies(num_blocks)
        self.results['attack_strategies_p2s'] = {
            name: {
                'description': r.description,
                'total_cost_eth': r.total_cost_eth,
                'total_gain_eth': r.total_gain_eth,
                'attempts': r.attempts,
                'successes': r.successes,
                'net_profit_eth': r.net_profit_eth,
                'cost_per_attempt_eth': r.cost_per_attempt_eth,
                'gain_per_success_eth': r.gain_per_success_eth,
                'cost_per_success_eth': r.cost_per_success_eth,
            }
            for name, r in strategy_results_p2s.items()
        }
        self.results['attack_strategies_p2s_note'] = (
            "In P2S only blind insert is applicable. Front-run, sandwich, arbitrage "
            "are not applicable (B1 has only PHTs; cannot target). "
            "Blind insert: gas paid for PHT inclusion; if attacker does not reveal after B1, "
            "tx is not processed but gas is still paid (single gas fee)."
        )

        self.calculate_metrics()
        self.save_results()
        self.print_summary()
        self.print_attack_strategies_summary()
        return self.results

    def select_proposer(self, protocol: str) -> str:
        """Select proposer by round-robin (one node = one node, no stake)."""
        protocol_validators = sorted([v_id for v_id, v in self.validators.items() if v['protocol'] == protocol])
        if not protocol_validators:
            return list(self.validators.keys())[0]
        if protocol == "P2S":
            idx = self._p2s_proposer_index % len(protocol_validators)
            self._p2s_proposer_index += 1
            return protocol_validators[idx]
        else:
            idx = self._eth_proposer_index % len(protocol_validators)
            self._eth_proposer_index += 1
            return protocol_validators[idx]
    
    def print_summary(self):
        """Print simulation summary"""
        print("\n" + "=" * 80)
        print("SIMULATION SUMMARY")
        print("=" * 80)
        
        print("\n📊 PROFIT DECENTRALIZATION (Gini Coefficient):")
        for protocol_key in ['p2s', 'ethereum_pos']:
            protocol_label = 'P2S' if protocol_key == 'p2s' else 'Ethereum PoS'
            gini = self.results['profit_distribution'][protocol_key]['gini_coefficient']
            print(f"  {protocol_label}: {gini:.4f} (lower = more decentralized)")
        
        print("\n💰 MEV REORDERING OPPORTUNITIES:")
        for protocol_key in ['p2s', 'ethereum_pos']:
            protocol_label = 'P2S' if protocol_key == 'p2s' else 'Ethereum PoS'
            mean_mev = self.results['mev_reordering'][protocol_key]['mean_mev']
            print(f"  {protocol_label}: ${mean_mev:.2f} per block")
        
        print("\n⏱️ SYSTEM OVERHEAD:")
        for protocol_key in ['p2s', 'ethereum_pos']:
            protocol_label = 'P2S' if protocol_key == 'p2s' else 'Ethereum PoS'
            mean_latency = self.results['overhead_metrics'][protocol_key]['mean_latency']
            mean_cost = self.results['overhead_metrics'][protocol_key]['mean_cost']
            print(f"  {protocol_label}: {mean_latency:.3f}s latency, ${mean_cost:.4f} cost per block")

    def print_attack_strategies_summary(self):
        """Print cost and gain: Ethereum PoS (all strategies) vs P2S (blind insert only)."""
        strategies = self.results.get('attack_strategies', {})
        if strategies:
            print("\n📌 MEV ATTACK STRATEGIES — Ethereum PoS (targeted only; no blind insert):")
            print("  (On Ethereum the mempool is visible, so rational attackers use front_run/sandwich, not blind insert.)")
            for name, s in strategies.items():
                net = s['net_profit_eth']
                print(f"  • {name}: cost={s['total_cost_eth']:.6f} ETH, gain={s['total_gain_eth']:.6f} ETH, "
                      f"net={net:.6f} ETH | attempts={s['attempts']}, successes={s['successes']}")
        strategies_p2s = self.results.get('attack_strategies_p2s', {})
        note = self.results.get('attack_strategies_p2s_note', '')
        if strategies_p2s:
            print("\n📌 MEV ATTACK STRATEGIES — P2S (only blind insert; no target from B1):")
            print(f"  {note}")
            for name, s in strategies_p2s.items():
                net = s['net_profit_eth']
                print(f"  • {name}: cost={s['total_cost_eth']:.6f} ETH, gain={s['total_gain_eth']:.6f} ETH, "
                      f"net={net:.6f} ETH | attempts={s['attempts']}, successes={s['successes']}")

    def calculate_metrics(self):
        """Calculate aggregate research metrics"""
        # Profit distribution metrics
        for protocol in ['P2S', 'Ethereum PoS']:
            protocol_key = protocol.lower().replace(' ', '_')
            protocol_validators = [v for v in self.validators.values() if v['protocol'] == protocol]
            profits = [v['net_profit'] for v in protocol_validators]
            
            self.results['profit_distribution'][protocol_key] = {
                'profits': profits,
                'gini_coefficient': self.calculate_gini_coefficient(profits),
                'mean_profit': statistics.mean(profits) if profits else 0,
                'std_profit': statistics.stdev(profits) if len(profits) > 1 else 0,
                'min_profit': min(profits) if profits else 0,
                'max_profit': max(profits) if profits else 0,
                'total_rewards': sum(v['total_rewards'] for v in protocol_validators),
                'total_costs': sum(v['total_gas_costs'] for v in protocol_validators)
            }
        
        # MEV reordering metrics
        for protocol_data, protocol_name in [(self.results['p2s_data'], 'p2s'),
                                            (self.results['ethereum_pos_data'], 'ethereum_pos')]:
            mev_opportunities = [block['mev_opportunity'] for block in protocol_data]
            self.results['mev_reordering'][protocol_name] = {
                'opportunities': mev_opportunities,
                'mean_mev': statistics.mean(mev_opportunities) if mev_opportunities else 0,
                'total_mev': sum(mev_opportunities),
                'blocks_with_mev': sum(1 for mev in mev_opportunities if mev > 0)
            }
        
        # Overhead metrics
        for protocol_data, protocol_name in [(self.results['p2s_data'], 'p2s'),
                                            (self.results['ethereum_pos_data'], 'ethereum_pos')]:
            latencies = [block['network_latency'] for block in protocol_data]
            costs = [block['gas_cost'] for block in protocol_data]
            times = [block['total_time'] for block in protocol_data]
            
            self.results['overhead_metrics'][protocol_name] = {
                'mean_latency': statistics.mean(latencies) if latencies else 0,
                'mean_cost': statistics.mean(costs) if costs else 0,
                'mean_time': statistics.mean(times) if times else 0,
                'total_cost': sum(costs),
                'p95_latency': sorted(latencies)[int(len(latencies) * 0.95)] if latencies else 0,
                'p99_latency': sorted(latencies)[int(len(latencies) * 0.99)] if latencies else 0
            }
    
    def save_results(self):
        """Save results to JSON"""
        os.makedirs('data', exist_ok=True)
        filename = f"data/simulation_{self.results['metadata']['timestamp']}.json"
        
        # Convert to JSON-serializable format
        json_results = json.loads(json.dumps(self.results, default=str))
        
        with open(filename, 'w') as f:
            json.dump(json_results, f, indent=2)
        
        print(f"\n💾 Results saved to {filename}")

def main():
    """Main function"""
    import sys
    
    num_blocks = 1000
    if len(sys.argv) > 1:
        try:
            num_blocks = int(sys.argv[1])
        except ValueError:
            print("Error: Number of blocks must be an integer")
            sys.exit(1)
    
    simulator = P2SSimulator()
    results = simulator.run_simulation(num_blocks)
    
    print(f"\n✅ Simulation complete!")
    print(f"Run the plotting scripts to generate visualizations")

if __name__ == "__main__":
    main()
