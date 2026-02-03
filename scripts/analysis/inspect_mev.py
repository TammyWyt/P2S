#!/usr/bin/env python3
"""
MEV Inspector for Ethereum and P2S Testnet
Inspired by mev-inspect-py, detects MEV activities in blocks
"""

import json
import os
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, asdict
from collections import defaultdict
from web3 import Web3
from web3.exceptions import BlockNotFound, TransactionNotFound
from web3.types import HexBytes

def to_hex_string(value) -> str:
    """Convert Web3 HexBytes or bytes to hex string"""
    if isinstance(value, HexBytes):
        return value.hex()
    elif isinstance(value, bytes):
        return value.hex()
    elif hasattr(value, 'hex'):
        return value.hex()
    else:
        return str(value)

@dataclass
class MinerPayment:
    """Miner payment (coinbase transfer + gas fees)"""
    block_number: int
    miner_address: str
    coinbase_transfer: float  # ETH
    total_gas_fees: float  # ETH
    total_payment: float  # ETH

@dataclass
class Swap:
    """Token swap detected"""
    tx_hash: str
    block_number: int
    sender: str
    protocol: str
    token_in: str
    token_out: str
    amount_in: float
    amount_out: float
    profit_potential: float  # ETH

@dataclass
class Arbitrage:
    """Arbitrage opportunity detected"""
    tx_hash: str
    block_number: int
    sender: str
    profit_token: str
    profit_amount: float  # ETH
    path: List[str]  # Token addresses in arbitrage path

@dataclass
class SandwichAttack:
    """Sandwich attack detected"""
    tx_hash: str
    block_number: int
    attacker: str
    target_tx: str
    front_run_tx: Optional[str]
    back_run_tx: Optional[str]
    profit: float  # ETH

@dataclass
class MEVBlockAnalysis:
    """Complete MEV analysis for a block"""
    block_number: int
    timestamp: int
    network: str  # "ethereum" or "p2s"
    miner_payments: List[MinerPayment]
    swaps: List[Swap]
    arbitrages: List[Arbitrage]
    sandwich_attacks: List[SandwichAttack]
    total_mev: float  # Total MEV extracted in ETH
    mev_per_tx: float  # Average MEV per transaction

class MEVInspector:
    """MEV Inspector for analyzing blocks"""
    
    # Common DEX router addresses (mainnet)
    DEX_ROUTERS = {
        "0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D": "UniswapV2",
        "0xE592427A0AEce92De3Edee1F18E0157C05861564": "UniswapV3",
        "0xd9e1cE17f2641f24aE83637ab66a2cca9C378B9F": "SushiSwap",
        "0x11111112542D85B3EF69AE05771c2dCCff4fAa26": "1inch",
        "0x881D40237659C251811CEC9c364ef91dC08D300C": "Metamask",
    }
    
    # Common token addresses
    WETH = "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2"
    USDC = "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"
    USDT = "0xdAC17F958D2ee523a2206206994597C13D831ec7"
    DAI = "0x6B175474E89094C44Da98b954EedeAC495271d0F"
    
    def __init__(self, rpc_url: str, network: str = "ethereum"):
        """
        Initialize MEV Inspector
        
        Args:
            rpc_url: RPC endpoint URL
            network: Network name ("ethereum" or "p2s")
        """
        self.w3 = Web3(Web3.HTTPProvider(rpc_url))
        self.network = network
        self.eth_price_usd = 2000.0  # Default, can be updated from on-chain
        
        # Verify connection
        if not self.w3.is_connected():
            raise ConnectionError(f"Failed to connect to RPC endpoint: {rpc_url}")
        
        print(f"✅ Connected to {network} network at {rpc_url}")
    
    def get_block(self, block_number: int) -> Dict:
        """Get block data with transactions"""
        try:
            block = self.w3.eth.get_block(block_number, full_transactions=True)
            # Convert to dict if needed
            if hasattr(block, '__dict__'):
                return dict(block)
            return block
        except BlockNotFound:
            print(f"⚠️  Block {block_number} not found")
            return None
        except Exception as e:
            print(f"⚠️  Error fetching block {block_number}: {e}")
            return None
    
    def get_transaction_receipt(self, tx_hash: str) -> Optional[Dict]:
        """Get transaction receipt"""
        try:
            return self.w3.eth.get_transaction_receipt(tx_hash)
        except TransactionNotFound:
            return None
    
    def analyze_miner_payments(self, block: Dict) -> List[MinerPayment]:
        """Analyze miner payments (coinbase transfers + gas fees)"""
        payments = []
        
        if not block:
            return payments
        
        miner = block.get('miner', '0x0')
        block_number = block.get('number', 0)
        
        # Calculate total gas fees
        total_gas_fees = 0.0
        coinbase_transfer = 0.0
        
        for tx in block.get('transactions', []):
            if isinstance(tx, dict):
                receipt = self.get_transaction_receipt(tx.get('hash'))
                if receipt:
                    gas_used = receipt.get('gasUsed', 0)
                    gas_price = tx.get('gasPrice', 0)
                    if isinstance(gas_price, int):
                        gas_fee = (gas_used * gas_price) / 1e18
                        total_gas_fees += gas_fee
                
                # Check for coinbase transfers
                if tx.get('to') == miner:
                    value = tx.get('value', 0)
                    if isinstance(value, int):
                        coinbase_transfer += value / 1e18
        
        total_payment = coinbase_transfer + total_gas_fees
        
        if total_payment > 0:
            payments.append(MinerPayment(
                block_number=block_number,
                miner_address=miner,
                coinbase_transfer=coinbase_transfer,
                total_gas_fees=total_gas_fees,
                total_payment=total_payment
            ))
        
        return payments
    
    def detect_swaps(self, block: Dict) -> List[Swap]:
        """Detect token swaps in block"""
        swaps = []
        
        if not block:
            return swaps
        
        for tx in block.get('transactions', []):
            if not isinstance(tx, dict):
                continue
            
            tx_hash = tx.get('hash', '')
            to_address = tx.get('to', '')
            
            # Check if transaction is to a known DEX router
            if to_address and to_address.lower() in [r.lower() for r in self.DEX_ROUTERS.keys()]:
                protocol = self.DEX_ROUTERS.get(to_address, "Unknown")
                
                # Try to decode swap (simplified - real implementation would decode calldata)
                receipt = self.get_transaction_receipt(tx_hash)
                if receipt and receipt.get('status') == 1:
                    # Check for token transfers in logs
                    token_in = None
                    token_out = None
                    amount_in = 0.0
                    amount_out = 0.0
                    
                    for log in receipt.get('logs', []):
                        # ERC20 Transfer event signature: Transfer(address,address,uint256)
                        if len(log.get('topics', [])) == 3:
                            # This is a simplified detection - real implementation would decode properly
                            pass
                    
                    # Estimate profit potential (simplified)
                    profit_potential = 0.0
                    if amount_in > 0 and amount_out > 0:
                        # Rough estimate: 0.1% of swap value as potential MEV
                        profit_potential = min(amount_in, amount_out) * 0.001
                    
                    swaps.append(Swap(
                        tx_hash=to_hex_string(tx_hash),
                        block_number=block.get('number', 0),
                        sender=to_hex_string(tx.get('from', '')) if tx.get('from') else '',
                        protocol=protocol,
                        token_in=token_in or "Unknown",
                        token_out=token_out or "Unknown",
                        amount_in=amount_in,
                        amount_out=amount_out,
                        profit_potential=profit_potential
                    ))
        
        return swaps
    
    def detect_arbitrages(self, block: Dict) -> List[Arbitrage]:
        """Detect arbitrage opportunities"""
        arbitrages = []
        
        if not block:
            return arbitrages
        
        # Group transactions by sender
        tx_by_sender = defaultdict(list)
        for tx in block.get('transactions', []):
            if isinstance(tx, dict):
                sender = tx.get('from', '')
                tx_by_sender[sender].append(tx)
        
        # Look for multiple swaps from same sender (potential arbitrage)
        for sender, txs in tx_by_sender.items():
            if len(txs) >= 2:
                # Check if these are swaps to different DEXes
                swap_txs = [tx for tx in txs if tx.get('to', '').lower() in [r.lower() for r in self.DEX_ROUTERS.keys()]]
                
                if len(swap_txs) >= 2:
                    # Potential arbitrage - estimate profit
                    profit = 0.0
                    path = []
                    
                    # Simplified: estimate profit from multiple swaps
                    for tx in swap_txs:
                        receipt = self.get_transaction_receipt(tx.get('hash'))
                        if receipt and receipt.get('status') == 1:
                            # Estimate profit (simplified)
                            value = tx.get('value', 0)
                            if isinstance(value, int):
                                profit += (value / 1e18) * 0.005  # 0.5% estimated profit
                    
                    if profit > 0:
                        arbitrages.append(Arbitrage(
                            tx_hash=to_hex_string(swap_txs[0].get('hash', '')),
                            block_number=block.get('number', 0),
                            sender=to_hex_string(sender) if sender else '',
                            profit_token=self.WETH,
                            profit_amount=profit,
                            path=path
                        ))
        
        return arbitrages
    
    def detect_sandwich_attacks(self, block: Dict) -> List[SandwichAttack]:
        """Detect sandwich attacks"""
        attacks = []
        
        if not block:
            return attacks
        
        transactions = block.get('transactions', [])
        
        # Look for patterns: high gas price transaction between two transactions from same sender
        for i, target_tx in enumerate(transactions):
            if not isinstance(target_tx, dict):
                continue
            
            target_gas_price = target_tx.get('gasPrice', 0)
            if isinstance(target_gas_price, int):
                target_gas_price = target_gas_price / 1e9  # Convert to gwei
            
            # High gas price might indicate MEV target
            if target_gas_price > 50:  # > 50 gwei
                # Look for transactions before and after from same sender
                target_sender = target_tx.get('from', '')
                
                front_run = None
                back_run = None
                
                # Check previous transactions
                for j in range(max(0, i-5), i):
                    prev_tx = transactions[j]
                    if isinstance(prev_tx, dict):
                        prev_sender = prev_tx.get('from', '')
                        if prev_sender == target_sender:
                            front_run = prev_tx.get('hash', '')
                            break
                
                # Check next transactions
                for j in range(i+1, min(len(transactions), i+6)):
                    next_tx = transactions[j]
                    if isinstance(next_tx, dict):
                        next_sender = next_tx.get('from', '')
                        if next_sender == target_sender:
                            back_run = next_tx.get('hash', '')
                            break
                
                if front_run or back_run:
                    # Estimate profit (simplified)
                    profit = 0.0
                    value = target_tx.get('value', 0)
                    if isinstance(value, int):
                        profit = (value / 1e18) * 0.01  # 1% of value as estimated profit
                    
                    attacks.append(SandwichAttack(
                        tx_hash=to_hex_string(target_tx.get('hash', '')),
                        block_number=block.get('number', 0),
                        attacker=to_hex_string(target_sender) if target_sender else '',
                        target_tx=to_hex_string(target_tx.get('hash', '')),
                        front_run_tx=to_hex_string(front_run) if front_run else None,
                        back_run_tx=to_hex_string(back_run) if back_run else None,
                        profit=profit
                    ))
        
        return attacks
    
    def analyze_block(self, block_number: int) -> MEVBlockAnalysis:
        """Analyze a single block for MEV"""
        print(f"🔍 Analyzing block {block_number} on {self.network}...")
        
        block = self.get_block(block_number)
        if not block:
            return None
        
        # Analyze different MEV types
        miner_payments = self.analyze_miner_payments(block)
        swaps = self.detect_swaps(block)
        arbitrages = self.detect_arbitrages(block)
        sandwich_attacks = self.detect_sandwich_attacks(block)
        
        # Calculate total MEV
        total_mev = 0.0
        total_mev += sum(p.total_payment for p in miner_payments)
        total_mev += sum(s.profit_potential for s in swaps)
        total_mev += sum(a.profit_amount for a in arbitrages)
        total_mev += sum(s.profit for s in sandwich_attacks)
        
        tx_count = len(block.get('transactions', []))
        mev_per_tx = total_mev / tx_count if tx_count > 0 else 0.0
        
        analysis = MEVBlockAnalysis(
            block_number=block_number,
            timestamp=block.get('timestamp', 0),
            network=self.network,
            miner_payments=miner_payments,
            swaps=swaps,
            arbitrages=arbitrages,
            sandwich_attacks=sandwich_attacks,
            total_mev=total_mev,
            mev_per_tx=mev_per_tx
        )
        
        print(f"  ✅ Found: {len(miner_payments)} miner payments, {len(swaps)} swaps, "
              f"{len(arbitrages)} arbitrages, {len(sandwich_attacks)} sandwich attacks")
        print(f"  💰 Total MEV: {total_mev:.6f} ETH")
        
        return analysis
    
    def analyze_blocks(self, start_block: int, end_block: int) -> List[MEVBlockAnalysis]:
        """Analyze multiple blocks"""
        analyses = []
        
        print(f"🔍 Analyzing blocks {start_block} to {end_block} on {self.network}...")
        
        for block_num in range(start_block, end_block + 1):
            try:
                analysis = self.analyze_block(block_num)
                if analysis:
                    analyses.append(analysis)
                time.sleep(0.1)  # Rate limiting
            except Exception as e:
                print(f"⚠️  Error analyzing block {block_num}: {e}")
                continue
        
        return analyses
    
    def save_results(self, analyses: List[MEVBlockAnalysis], output_file: str):
        """Save analysis results to JSON file"""
        os.makedirs(os.path.dirname(output_file) if os.path.dirname(output_file) else 'data', exist_ok=True)
        
        # Convert to dict format
        results = {
            'network': self.network,
            'timestamp': datetime.now().isoformat(),
            'total_blocks': len(analyses),
            'analyses': []
        }
        
        for analysis in analyses:
            analysis_dict = {
                'block_number': analysis.block_number,
                'timestamp': analysis.timestamp,
                'miner_payments': [asdict(p) for p in analysis.miner_payments],
                'swaps': [asdict(s) for s in analysis.swaps],
                'arbitrages': [asdict(a) for a in analysis.arbitrages],
                'sandwich_attacks': [asdict(s) for s in analysis.sandwich_attacks],
                'total_mev': analysis.total_mev,
                'mev_per_tx': analysis.mev_per_tx
            }
            results['analyses'].append(analysis_dict)
        
        with open(output_file, 'w') as f:
            json.dump(results, f, indent=2)
        
        print(f"💾 Results saved to {output_file}")

def main():
    """Main function"""
    import sys
    import argparse
    
    parser = argparse.ArgumentParser(description='MEV Inspector for Ethereum and P2S Testnet')
    parser.add_argument('--rpc', type=str, required=True, help='RPC endpoint URL')
    parser.add_argument('--network', type=str, default='ethereum', choices=['ethereum', 'p2s'],
                       help='Network name (ethereum or p2s)')
    parser.add_argument('--block', type=int, help='Single block number to analyze')
    parser.add_argument('--start', type=int, help='Start block number (for range)')
    parser.add_argument('--end', type=int, help='End block number (for range)')
    parser.add_argument('--output', type=str, default=None, help='Output file path')
    
    args = parser.parse_args()
    
    # Create inspector
    inspector = MEVInspector(args.rpc, args.network)
    
    # Determine output file
    if args.output is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        args.output = f"data/mev_inspection_{args.network}_{timestamp}.json"
    
    # Analyze blocks
    if args.block:
        analysis = inspector.analyze_block(args.block)
        if analysis:
            inspector.save_results([analysis], args.output)
    elif args.start and args.end:
        analyses = inspector.analyze_blocks(args.start, args.end)
        if analyses:
            inspector.save_results(analyses, args.output)
    else:
        print("❌ Please specify either --block or both --start and --end")
        sys.exit(1)
    
    print(f"\n✅ MEV inspection complete!")
    print(f"   Results saved to: {args.output}")

if __name__ == "__main__":
    main()
