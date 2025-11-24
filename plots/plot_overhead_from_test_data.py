#!/usr/bin/env python3
"""
Plot overhead metrics from test data (system_overhead_*.json)
"""

import json
import os
import glob
import matplotlib.pyplot as plt
import seaborn as sns
import numpy as np

# Set style with coherent colors
sns.set_theme(style="white")
P2S_COLOR = '#2ecc71'  # Green
ETH_COLOR = '#3498db'  # Blue

plt.rcParams['figure.dpi'] = 300
plt.rcParams['savefig.dpi'] = 300

def load_latest_test_data(data_dir="data"):
    """Load the latest system overhead test data"""
    files = glob.glob(f"{data_dir}/system_overhead_*.json")
    if not files:
        return None
    latest_file = max(files, key=os.path.getctime)
    with open(latest_file, 'r') as f:
        return json.load(f)

def plot_block_time_distribution(data):
    """Plot only block time distribution (no average comparison)"""
    p2s_block = data['p2s_overhead']['block']
    pos_block = data['pos_overhead']['block']
    
    # Calculate total block processing overhead (processing + network latency)
    # Note: This measures overhead WITHIN a 12-second slot, not the slot time itself
    # Ethereum PoS has fixed 12-second slots, but blocks take time to process and propagate
    p2s_blk_total_time = [b['total_processing_time'] + b['total_network_latency'] for b in p2s_block]
    pos_blk_total_time = [b['total_processing_time'] + b['total_network_latency'] for b in pos_block]
    
    analysis = data['analysis']
    p2s_proc_mean = analysis['block']['p2s']['processing_time']['mean']
    p2s_net_mean = analysis['block']['p2s']['network_latency']['mean']
    pos_proc_mean = analysis['block']['pos']['processing_time']['mean']
    pos_net_mean = analysis['block']['pos']['network_latency']['mean']
    
    p2s_total_mean = p2s_proc_mean + p2s_net_mean
    pos_total_mean = pos_proc_mean + pos_net_mean
    
    fig, ax = plt.subplots(figsize=(10, 7))
    
    # Block processing overhead distribution histogram
    ax.hist(pos_blk_total_time, bins=40, alpha=0.6, label='Current Ethereum', 
            color=ETH_COLOR, edgecolor='black', linewidth=1)
    ax.hist(p2s_blk_total_time, bins=40, alpha=0.6, label='P2S', 
            color=P2S_COLOR, edgecolor='black', linewidth=1)
    
    # Add mean lines
    ax.axvline(pos_total_mean, color=ETH_COLOR, linestyle='--', linewidth=2, 
               label=f'Ethereum Mean: {pos_total_mean:.3f}s')
    ax.axvline(p2s_total_mean, color=P2S_COLOR, linestyle='--', linewidth=2,
               label=f'P2S Mean: {p2s_total_mean:.3f}s')
    
    # Add statistics text with clarification
    overhead = ((p2s_total_mean - pos_total_mean) / pos_total_mean) * 100
    stats_text = f'Block Processing Overhead:\n'
    stats_text += f'(within 12s slot)\n\n'
    stats_text += f'Ethereum: {pos_total_mean:.3f}s\n'
    stats_text += f'  ({pos_proc_mean:.3f}s proc + {pos_net_mean:.3f}s net)\n'
    stats_text += f'P2S: {p2s_total_mean:.3f}s\n'
    stats_text += f'  ({p2s_proc_mean:.3f}s proc + {p2s_net_mean:.3f}s net)\n'
    stats_text += f'Overhead: {overhead:.1f}%'
    
    ax.text(0.98, 0.02, stats_text, transform=ax.transAxes, fontsize=10,
            verticalalignment='bottom', horizontalalignment='right',
            bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8))
    
    ax.set_xlabel('Block Processing Overhead (seconds)\n(processing + network latency within 12s slot)', 
                   fontsize=13, fontweight='bold')
    ax.set_ylabel('Frequency', fontsize=13, fontweight='bold')
    ax.set_title('Block Processing Overhead Distribution', fontsize=15, fontweight='bold', pad=15)
    ax.legend(fontsize=11, framealpha=0.9)
    ax.grid(True, alpha=0.3, linestyle='--')
    
    plt.tight_layout()
    os.makedirs('figures', exist_ok=True)
    plt.savefig('figures/overhead_block_time.png', dpi=300, bbox_inches='tight')
    plt.close()
    print("  ✓ Saved: figures/overhead_block_time.png")

def print_overhead_ratios(data):
    """Print overhead ratios instead of plotting"""
    overhead_ratios = data['analysis']['overhead_ratios']
    
    print("\n" + "=" * 80)
    print("OVERHEAD RATIOS")
    print("=" * 80)
    print(f"\nProcessing Time Overhead: {overhead_ratios['time_overhead_pct']:.1f}%")
    print(f"Gas Usage Overhead: {overhead_ratios['gas_overhead_pct']:.1f}%")
    print(f"Transaction Cost Overhead: {overhead_ratios['cost_overhead_pct']:.1f}%")
    print("=" * 80)

def main():
    """Main function"""
    data = load_latest_test_data()
    if not data:
        print("⚠ No system overhead test data found")
        print("   Run: python scripts/testing/test_system_overhead.py")
        return
    
    print("Creating overhead plots from test data...")
    plot_block_time_distribution(data)
    print_overhead_ratios(data)
    
    print("\n✅ Overhead plots created successfully!")

if __name__ == "__main__":
    main()

