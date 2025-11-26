#!/usr/bin/env python3
"""
P2S Simulation
Main simulation comparing P2S vs Ethereum PoS using real Ethereum block data
"""

import json
import time
import random
import statistics
from datetime import datetime
from typing import List, Dict, Any, Tuple
import os
from collections import defaultdict
import glob

class P2SSimulator:
    """Enhanced simulator that collects research metrics using real Ethereum data"""
    
    def __init__(self):
        self.network_latency_base = 0.1
        self.network_jitter = 0.05
        self.base_gas_price = 20  # gwei
        self.gas_cost_per_unit = 0.000001  # ETH per gas unit
        
        # Metrics storage
        self.results = {
            'p2s_data': [],
            'ethereum_pos_data': [],  # Standard Ethereum PoS (baseline)
            'profit_distribution': {
                'p2s': {},
                'ethereum_pos': {}
            },
            'mev_reordering': {
                'p2s': [],
                'ethereum_pos': []
            },
            'overhead_metrics': {
                'p2s': {},
                'ethereum_pos': {}
            },
            'metadata': {
                'timestamp': datetime.now().strftime("%Y%m%d_%H%M%S"),
                'description': "P2S simulation: P2S vs Ethereum PoS (using real Ethereum blocks)"
            }
        }
        
        # Validators/participants
        self.validators = {}
        self.transactions = {}
        self.block_rewards = defaultdict(float)
        
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
    
    def create_validator(self, validator_id: str, stake: float, protocol: str):
        """Create a validator with stake"""
        self.validators[validator_id] = {
            'id': validator_id,
            'stake': stake,
            'protocol': protocol,
            'blocks_proposed': 0,
            'total_rewards': 0.0,
            'total_gas_costs': 0.0,
            'net_profit': 0.0,
            'mev_extracted': 0.0
        }
    
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
            # Convert gasPrice from wei to gwei if needed
            gas_price = tx.get('gasPrice', 0)
            if gas_price > 1e15:  # Likely in wei, convert to gwei
                gas_price = gas_price / 1e9
            
            value = tx.get('value', 0)
            if isinstance(value, str):
                try:
                    value = int(value, 16) if value.startswith('0x') else int(value)
                except:
                    value = 0
            
            # If high value but low gas price, there's reordering potential
            if value > 1e18 and gas_price < 50:  # > 1 ETH value, < 50 gwei
                # Potential profit from front-running
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
        
        # Calculate costs (using real gas prices from transactions)
        gas_cost = sum(tx.get('gas_price', 20) * tx.get('gas_limit', 21000) * self.gas_cost_per_unit 
                      for tx in transactions)
        
        # Block reward (fixed + transaction fees)
        block_reward = 2.0 + sum(tx.get('gas_price', 20) * tx.get('gas_limit', 21000) * self.gas_cost_per_unit * 0.1 
                                for tx in transactions)
        
        # MEV reordering opportunity (should be low in P2S due to hidden details)
        mev_opportunity = self.calculate_reordering_opportunity(transactions) * 0.1  # Reduced by 90% in P2S
        
        # Update validator metrics
        if proposer_id in self.validators:
            self.validators[proposer_id]['blocks_proposed'] += 1
            self.validators[proposer_id]['total_rewards'] += block_reward
            self.validators[proposer_id]['total_gas_costs'] += gas_cost
            self.validators[proposer_id]['net_profit'] = (self.validators[proposer_id]['total_rewards'] - 
                                                          self.validators[proposer_id]['total_gas_costs'])
        
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
        
        # Calculate costs (using real gas prices from transactions)
        gas_cost = sum(tx.get('gas_price', 20) * tx.get('gas_limit', 21000) * self.gas_cost_per_unit 
                      for tx in transactions)
        
        # Block reward
        block_reward = 2.0 + sum(tx.get('gas_price', 20) * tx.get('gas_limit', 21000) * self.gas_cost_per_unit * 0.1 
                                for tx in transactions)
        
        # MEV reordering opportunity (full visibility - can see all transaction details)
        mev_opportunity = self.calculate_reordering_opportunity(transactions) * 1.0  # 100% of potential
        
        # Update validator metrics
        if proposer_id in self.validators:
            self.validators[proposer_id]['blocks_proposed'] += 1
            self.validators[proposer_id]['total_rewards'] += block_reward
            self.validators[proposer_id]['total_gas_costs'] += gas_cost
            self.validators[proposer_id]['net_profit'] = (self.validators[proposer_id]['total_rewards'] - 
                                                          self.validators[proposer_id]['total_gas_costs'])
            self.validators[proposer_id]['mev_extracted'] += mev_opportunity * 0.6  # Assume 60% extraction rate
        
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
    
    def run_simulation(self, num_blocks: int = 1000):
        """Run comprehensive simulation using real Ethereum block data"""
        print("=" * 80)
        print("P2S SIMULATION")
        print("=" * 80)
        print(f"Simulating {num_blocks} blocks per protocol")
        print("Using real Ethereum block data")
        print("=" * 80)
        
        # Load real Ethereum blocks
        ethereum_blocks = self.load_ethereum_blocks()
        if not ethereum_blocks:
            print("❌ No Ethereum block data available. Please run extract_ethereum_blocks.py first.")
            return None
        
        # Use first N blocks
        ethereum_blocks = ethereum_blocks[:num_blocks]
        
        # Create validators for each protocol
        num_validators = 10
        for i in range(num_validators):
            stake = random.uniform(1000, 10000)
            self.create_validator(f"p2s_validator_{i}", stake, "P2S")
            self.create_validator(f"ethereum_pos_validator_{i}", stake, "Ethereum PoS")
        
        # Run simulations
        congestion_levels = [0.0, 0.1, 0.3, 0.5, 0.7]
        
        for i, ethereum_block in enumerate(ethereum_blocks):
            congestion = random.choice(congestion_levels)
            
            # Select proposers (weighted by stake)
            p2s_proposer = self.select_proposer("P2S")
            ethereum_pos_proposer = self.select_proposer("Ethereum PoS")
            
            # Simulate blocks using the SAME Ethereum block data
            p2s_block = self.simulate_p2s_block(i, p2s_proposer, ethereum_block, congestion)
            ethereum_pos_block = self.simulate_ethereum_pos_block(i, ethereum_pos_proposer, ethereum_block, congestion)
            
            self.results['p2s_data'].append(p2s_block)
            self.results['ethereum_pos_data'].append(ethereum_pos_block)
            
            if (i + 1) % 100 == 0 or (i + 1) == len(ethereum_blocks):
                print(f"Processed {i + 1}/{len(ethereum_blocks)} blocks...")
        
        # Calculate aggregate metrics
        self.calculate_metrics()
        
        # Save results
        self.save_results()
        
        # Print summary
        self.print_summary()
        
        return self.results
    
    def select_proposer(self, protocol: str) -> str:
        """Select proposer weighted by stake"""
        protocol_validators = [(v_id, v) for v_id, v in self.validators.items() 
                              if v['protocol'] == protocol]
        if not protocol_validators:
            return list(self.validators.keys())[0]
        
        # Weighted random selection
        total_stake = sum(v['stake'] for _, v in protocol_validators)
        r = random.uniform(0, total_stake)
        cumsum = 0
        for v_id, v in protocol_validators:
            cumsum += v['stake']
            if r <= cumsum:
                return v_id
        return protocol_validators[-1][0]
    
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
