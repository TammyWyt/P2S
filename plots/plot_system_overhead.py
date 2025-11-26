#!/usr/bin/env python3
"""
Research Question 3: System Overhead
Grouped bar chart comparing latency and cost between P2S and Ethereum PoS
"""

import json
import os
import numpy as np
import matplotlib.pyplot as plt
from typing import Dict
import glob

plt.rcParams['figure.dpi'] = 300
plt.rcParams['savefig.dpi'] = 300
plt.rcParams['font.size'] = 14
plt.rcParams['font.family'] = 'sans-serif'

def load_latest_research_data(data_dir="data"):
    """Load the latest research metrics data"""
    files = glob.glob(f"{data_dir}/simulation_*.json")
    if not files:
        return None
    latest_file = max(files, key=os.path.getctime)
    with open(latest_file, 'r') as f:
        return json.load(f)

def plot_system_overhead(data: Dict):
    """Grouped bar chart: Clean comparison of key overhead metrics"""
    P2S_COLOR = '#2ecc71'
    ETH_COLOR = '#3498db'
    
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))
    
    protocols = ['p2s', 'ethereum_pos']
    protocol_labels = ['P2S', 'Ethereum PoS']
    colors = [P2S_COLOR, ETH_COLOR]
    
    # Extract overhead data
    mean_latencies = []
    mean_costs = []
    
    for protocol in protocols:
        if protocol in data.get('overhead_metrics', {}):
            mean_latencies.append(data['overhead_metrics'][protocol].get('mean_latency', 0))
            mean_costs.append(data['overhead_metrics'][protocol].get('mean_cost', 0))
        else:
            mean_latencies.append(0)
            mean_costs.append(0)
    
    # Plot 1: Network Latency
    bars1 = ax1.bar(protocol_labels, mean_latencies, color=colors, alpha=0.85, 
                   edgecolor='black', linewidth=2)
    ax1.set_ylabel('Mean Network Latency (seconds)', fontsize=16, fontweight='bold')
    ax1.grid(True, alpha=0.2, axis='y', linestyle='--', linewidth=0.8)
    ax1.set_ylim(0, max(mean_latencies) * 1.2 if mean_latencies else 1)
    
    # Plot 2: Gas Cost
    bars2 = ax2.bar(protocol_labels, mean_costs, color=colors, alpha=0.85, 
                   edgecolor='black', linewidth=2)
    ax2.set_ylabel('Mean Gas Cost per Block (ETH)', fontsize=16, fontweight='bold')
    ax2.grid(True, alpha=0.2, axis='y', linestyle='--', linewidth=0.8)
    ax2.set_ylim(0, max(mean_costs) * 1.2 if mean_costs else 1)
    
    # Clean up spines
    for ax in [ax1, ax2]:
        for spine in ax.spines.values():
            spine.set_linewidth(1.2)
    
    plt.tight_layout()
    os.makedirs('figures', exist_ok=True)
    plt.savefig('figures/system_overhead.png', dpi=300, bbox_inches='tight', facecolor='white')
    plt.close()

def main():
    data = load_latest_research_data()
    if data:
        plot_system_overhead(data)
    else:
        print("❌ No data found. Run simulation.py first.")

if __name__ == "__main__":
    main()
