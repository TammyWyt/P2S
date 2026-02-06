#!/usr/bin/env python3
"""
Plot overhead metrics from simulation data (simulation_*.json)
"""

import json
import os
import glob
import matplotlib.pyplot as plt
import seaborn as sns
import numpy as np
import statistics

# Set style with coherent colors (matching MEV plots)
sns.set_theme(style="ticks")
# Colors from seaborn vlag palette (diverging blue to red)
VLAG_PALETTE = sns.color_palette("vlag", n_colors=10)
ETH_COLOR = VLAG_PALETTE[1]   # Ethereum (blue end)
P2S_COLOR = VLAG_PALETTE[-2]  # P2S (red end)

plt.rcParams['figure.dpi'] = 300
plt.rcParams['savefig.dpi'] = 300
plt.rcParams['font.size'] = 18

def load_latest_simulation_data(data_dir="data"):
    """Load the latest simulation data"""
    files = glob.glob(f"{data_dir}/simulation_*.json")
    if not files:
        return None
    latest_file = max(files, key=os.path.getctime)
    with open(latest_file, 'r') as f:
        return json.load(f)

def plot_block_time_distribution(data):
    """Plot only block time distribution (no average comparison)"""
    # Extract block data from simulation.py format
    p2s_blocks = data.get('p2s_data', [])
    pos_blocks = data.get('ethereum_pos_data', [])
    
    if not p2s_blocks or not pos_blocks:
        print("⚠ No block data found in simulation data")
        return
    
    # Calculate total block processing overhead (processing + network latency)
    # Note: This measures overhead WITHIN a 12-second slot, not the slot time itself
    # Ethereum PoS has fixed 12-second slots, but blocks take time to process and propagate
    # processing_time = total_time - network_latency
    p2s_blk_total_time = []
    pos_blk_total_time = []
    
    for block in p2s_blocks:
        total_time = block.get('total_time', 0)
        network_latency = block.get('network_latency', 0)
        processing_time = total_time - network_latency
        p2s_blk_total_time.append(processing_time + network_latency)
    
    for block in pos_blocks:
        total_time = block.get('total_time', 0)
        network_latency = block.get('network_latency', 0)
        processing_time = total_time - network_latency
        pos_blk_total_time.append(processing_time + network_latency)
    
    # Calculate means
    p2s_proc_mean = statistics.mean([b.get('total_time', 0) - b.get('network_latency', 0) for b in p2s_blocks])
    p2s_net_mean = statistics.mean([b.get('network_latency', 0) for b in p2s_blocks])
    pos_proc_mean = statistics.mean([b.get('total_time', 0) - b.get('network_latency', 0) for b in pos_blocks])
    pos_net_mean = statistics.mean([b.get('network_latency', 0) for b in pos_blocks])
    
    p2s_total_mean = p2s_proc_mean + p2s_net_mean
    pos_total_mean = pos_proc_mean + pos_net_mean
    
    fig, ax = plt.subplots(figsize=(10, 7))
    
    # Block processing overhead distribution histogram
    ax.hist(pos_blk_total_time, bins=40, alpha=0.6, label='Ethereum', 
            color=ETH_COLOR, edgecolor='white', linewidth=1.2)
    ax.hist(p2s_blk_total_time, bins=40, alpha=0.6, label='P2S', 
            color=P2S_COLOR, edgecolor='white', linewidth=1.2)
    
    # Add mean lines
    ax.axvline(pos_total_mean, color=ETH_COLOR, linestyle='--', linewidth=2, 
               label=f'Ethereum Mean: {pos_total_mean:.3f}s')
    ax.axvline(p2s_total_mean, color=P2S_COLOR, linestyle='--', linewidth=2,
               label=f'P2S Mean: {p2s_total_mean:.3f}s')
    
    ax.set_xlabel('Block Processing Overhead (seconds)\n(processing + network latency within 12s slot)', 
                   fontsize=24, fontweight='bold')
    ax.set_ylabel('Frequency', fontsize=24, fontweight='bold')
    ax.tick_params(axis='both', labelsize=20)
    ax.legend(fontsize=18, framealpha=0.9)
    sns.despine(ax=ax)
    
    plt.tight_layout()
    os.makedirs('figures', exist_ok=True)
    plt.savefig('figures/overhead_block_time.pdf', dpi=300, bbox_inches='tight')
    plt.close()
    print("  ✓ Saved: figures/overhead_block_time.pdf")

def print_overhead_ratios(data):
    """Print overhead ratios instead of plotting"""
    # Calculate overhead ratios from simulation data
    p2s_blocks = data.get('p2s_data', [])
    pos_blocks = data.get('ethereum_pos_data', [])
    
    if not p2s_blocks or not pos_blocks:
        print("⚠ No block data found for overhead ratios")
        return
    
    # Calculate means
    p2s_times = [b.get('total_time', 0) for b in p2s_blocks]
    pos_times = [b.get('total_time', 0) for b in pos_blocks]
    p2s_gas = [b.get('gas_cost', 0) for b in p2s_blocks]
    pos_gas = [b.get('gas_cost', 0) for b in pos_blocks]
    
    p2s_mean_time = statistics.mean(p2s_times) if p2s_times else 0
    pos_mean_time = statistics.mean(pos_times) if pos_times else 0
    p2s_mean_gas = statistics.mean(p2s_gas) if p2s_gas else 0
    pos_mean_gas = statistics.mean(pos_gas) if pos_gas else 0
    
    time_overhead = ((p2s_mean_time - pos_mean_time) / pos_mean_time * 100) if pos_mean_time > 0 else 0
    gas_overhead = ((p2s_mean_gas - pos_mean_gas) / pos_mean_gas * 100) if pos_mean_gas > 0 else 0
    
    print("\n" + "=" * 80)
    print("OVERHEAD RATIOS")
    print("=" * 80)
    print(f"\nProcessing Time Overhead: {time_overhead:.1f}%")
    print(f"Gas Usage Overhead: {gas_overhead:.1f}%")
    print(f"Transaction Cost Overhead: {gas_overhead:.1f}%")
    print("=" * 80)

def main():
    """Main function"""
    data = load_latest_simulation_data()
    if not data:
        print("⚠ No simulation data found")
        print("   Run: python scripts/testing/simulation.py")
        return
    
    print("Creating overhead plots from simulation data...")
    plot_block_time_distribution(data)
    print_overhead_ratios(data)
    
    print("\n✅ Overhead plots created successfully!")

if __name__ == "__main__":
    main()

