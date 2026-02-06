#!/usr/bin/env python3
"""
Research Question 1: Profit Decentralization
Lorenz Curve comparing profit distribution between P2S and Ethereum PoS
"""

import json
import os
import numpy as np
import matplotlib.pyplot as plt
from typing import Dict
import glob

plt.rcParams['figure.dpi'] = 300
plt.rcParams['savefig.dpi'] = 300
plt.rcParams['font.size'] = 20
plt.rcParams['font.family'] = 'sans-serif'

def load_latest_research_data(data_dir="data"):
    """Load the latest research metrics data"""
    files = glob.glob(f"{data_dir}/simulation_*.json")
    if not files:
        return None
    latest_file = max(files, key=os.path.getctime)
    with open(latest_file, 'r') as f:
        return json.load(f)

def plot_profit_decentralization(data: Dict):
    """Lorenz Curve: Clean visualization for profit distribution"""
    P2S_COLOR = '#2ecc71'
    ETH_COLOR = '#3498db'
    
    fig, ax = plt.subplots(figsize=(10, 10))
    
    # Perfect equality line
    ax.plot([0, 1], [0, 1], 'k--', linewidth=2, alpha=0.4)
    
    protocols = ['p2s', 'ethereum_pos']
    protocol_labels = ['P2S', 'Ethereum PoS']
    colors = [P2S_COLOR, ETH_COLOR]
    
    has_data = False
    for protocol, label, color in zip(protocols, protocol_labels, colors):
        if protocol in data.get('profit_distribution', {}):
            profits = data['profit_distribution'][protocol].get('profits', [])
            
            if profits and len(profits) > 0:
                # Use absolute values for Lorenz curve (normalize to positive)
                profits_abs = [abs(p) for p in profits]
                if sum(profits_abs) > 0:
                    has_data = True
                    profits_sorted = sorted(profits_abs)
                    n = len(profits_sorted)
                    cumsum_profits = np.cumsum(profits_sorted)
                    cumsum_profits = cumsum_profits / cumsum_profits[-1]
                    cumsum_pop = np.arange(1, n + 1) / n
                    
                    ax.plot(cumsum_pop, cumsum_profits, label=label, 
                           linewidth=3.5, color=color, marker='o', markersize=4, markevery=max(1, n//20))
    
    if not has_data:
        print("⚠ No profit distribution data found")
        return
    
    ax.set_xlabel('Cumulative Fraction of Validators', fontsize=26, fontweight='bold')
    ax.set_ylabel('Cumulative Fraction of Profits', fontsize=26, fontweight='bold')
    ax.tick_params(axis='both', labelsize=22)
    ax.legend(loc='lower right', fontsize=22, frameon=True, fancybox=True, shadow=True)
    ax.grid(True, alpha=0.2, linestyle='--', linewidth=0.8)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_aspect('equal')
    
    # Clean up spines
    for spine in ax.spines.values():
        spine.set_linewidth(1.2)
    
    plt.tight_layout()
    os.makedirs('figures', exist_ok=True)
    plt.savefig('figures/profit_decentralization.pdf', dpi=300, bbox_inches='tight', facecolor='white')
    plt.close()

def main():
    data = load_latest_research_data()
    if data:
        plot_profit_decentralization(data)
    else:
        print("❌ No data found. Run simulation.py first.")

if __name__ == "__main__":
    main()
