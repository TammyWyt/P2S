#!/usr/bin/env python3
"""Per-revert cost: P2S (floor fee) vs Ethereum PoS, normal fee regime.

Answers directly: does a benign slippage revert cost the user more under P2S
than on Ethereum today? For each reverted DEX swap we compare the absolute
per-revert cost (USD):

  Ethereum : cost = gas_used * eff_price                  (base burned on
             consumed gas, priority to validator; standard EIP-1559 revert)
  P2S      : cost = max(F_res, F_base) + F_tip            (eq:total-fee; the
             reservation is a FLOOR on the base fee, charged in B1, credited
             against the base owed on reveal -- not an additive surcharge)

Reconstructed from the precomputed fields: F_base = f_res * util / phi,
F_tip = cost_today - F_base, so P2S cost = cost_today + max(0, F_res - F_base).
A revert consuming at least phi*g_limit (util >= 20%) meets the floor and its
P2S cost equals its Ethereum cost. Writes one CDF PDF. No network.
"""
import json
import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import seaborn as sns

# House style — matches plots/plot_welfare.py.
FS_LABEL = 24
FS_TICK = 20
FS_LEGEND = 18
_DEEP = sns.color_palette("deep")
C_POS = _DEEP[3]   # red-orange — Ethereum PoS
C_P2S = _DEEP[0]   # steel blue — P2S

PHI = 0.20
_HERE = os.path.dirname(os.path.abspath(__file__))

REGIMES = [
    ("low-fee", "data/revert_cost_analysis.json", 1754.9, "revert_cost_lowfee.pdf"),
]


def is_slippage(r):
    return r["category"] == "slippage" or (
        r["category"] == "in_block_state_dependent" and r["is_dex"])


def costs(r):
    fres, today, util = r["f_res_eth"], r["cost_today_eth"], r["utilization"]
    if not today or fres is None or not util:
        return None
    f_base = fres * util / PHI                       # gas_used * base_fee
    p2s = today + max(0.0, fres - f_base)            # max(F_res,F_base)+F_tip
    return today, p2s


def ecdf(xs):
    xs = sorted(xs)
    return xs, [(i + 1) / len(xs) for i in range(len(xs))]


def main():
    for regime, path, eth_usd, fname in REGIMES:
        rows = [r for r in json.load(open(os.path.join(_HERE, "..", path)))["reverted_txs"]
                if is_slippage(r)]
        pairs = [c for c in (costs(r) for r in rows) if c is not None]
        eth = [today * eth_usd for today, _ in pairs]
        p2s = [p * eth_usd for _, p in pairs]

        sns.set_theme(style="ticks")
        fig, ax = plt.subplots(figsize=(7, 5))
        for xs_src, label, col, ls in [
            (eth, "Ethereum", C_POS, "-"),
            (p2s, "P2S", C_P2S, "--"),
        ]:
            xs, ys = ecdf(xs_src)
            ax.plot(xs, ys, label=label, color=col, lw=2.4, linestyle=ls)
        ax.set_xscale("log")
        ax.set_ylim(0, 1.02)
        ax.set_xlabel("Per-revert cost (USD)", fontsize=FS_LABEL, fontweight="bold")
        ax.set_ylabel("CDF", fontsize=FS_LABEL, fontweight="bold")
        ax.tick_params(labelsize=FS_TICK)
        ax.legend(fontsize=FS_LEGEND, loc="lower right", frameon=False)
        ax.grid(True, alpha=0.18, linestyle="--", color="gray")
        ax.set_axisbelow(True)
        sns.despine(ax=ax)
        plt.tight_layout()

        for base in [os.path.join(_HERE, "..", "figures"),
                     os.path.join(_HERE, "..", "..", "P2S_Overleaf", "Figures")]:
            os.makedirs(base, exist_ok=True)
            plt.savefig(os.path.join(base, fname), dpi=300, bbox_inches="tight")
        plt.close()
        # console summary: median cost each, and how many pay strictly more
        eth_s, p2s_s = sorted(eth), sorted(p2s)
        med = len(eth) // 2
        more = sum(1 for a, b in zip(eth, p2s) if b > a + 1e-12) / len(eth)
        print(f"{regime:<11} n={len(eth):4}  median ETH ${eth_s[med]:.2f} -> P2S ${p2s_s[med]:.2f}"
              f"   {100*more:.0f}% pay more under P2S   wrote {fname}")


if __name__ == "__main__":
    main()
