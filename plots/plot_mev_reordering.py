#!/usr/bin/env python3
"""
Research Question 2: MEV Reordering Opportunities
Bar chart comparing mean MEV opportunity per block between P2S and Ethereum PoS
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

def plot_mev_reordering(data: Dict):
    """Bar chart: Clean comparison of MEV opportunities"""
    P2S_COLOR = '#2ecc71'
    ETH_COLOR = '#3498db'
    
    fig, ax = plt.subplots(figsize=(8, 6))
    
    protocols = ['p2s', 'ethereum_pos']
    protocol_labels = ['P2S', 'Ethereum PoS']
    colors = [P2S_COLOR, ETH_COLOR]
    
    mean_mev = []
    std_mev = []
    for protocol in protocols:
        if protocol in data.get('mev_reordering', {}):
            opportunities = data['mev_reordering'][protocol].get('opportunities', [])
            mean_val = np.mean(opportunities) if opportunities else 0
            std_val = np.std(opportunities) if len(opportunities) > 1 else 0
            mean_mev.append(mean_val)
            std_mev.append(std_val)
        else:
            mean_mev.append(0)
            std_mev.append(0)
    
    # Create bar chart with error bars
    bars = ax.bar(protocol_labels, mean_mev, color=colors, alpha=0.85, 
                  edgecolor='black', linewidth=2, yerr=std_mev, 
                  capsize=12, error_kw={'linewidth': 2.5, 'capthick': 2})
    
    ax.set_ylabel('Mean MEV Opportunity per Block (ETH)', fontsize=16, fontweight='bold')
    ax.grid(True, alpha=0.2, axis='y', linestyle='--', linewidth=0.8)
    ax.set_ylim(0, max(mean_mev) * 1.25 if mean_mev else 1)
    
    # Clean up spines
    for spine in ax.spines.values():
        spine.set_linewidth(1.2)
    
    plt.tight_layout()
    os.makedirs('figures', exist_ok=True)
    plt.savefig('figures/mev_reordering.png', dpi=300, bbox_inches='tight', facecolor='white')
    plt.close()

def main():
    data = load_latest_research_data()
    if data:
        plot_mev_reordering(data)
    else:
        print("❌ No data found. Run simulation.py first.")

if __name__ == "__main__":
    main()
