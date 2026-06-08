#!/usr/bin/env python3
"""Compare benign-user revert cost under three fee models, in two fee regimes.

Models (per reverted transaction, e.g. a DEX swap that trips its slippage bound):

  ETH today    : cost = gas_used * eff_price
                 (state rolled back; gas_used FORFEITED; base-fee portion BURNED,
                  priority to validator; only the UNUSED gas_limit-gas_used is
                  refunded -- there is NO refund of base fee on consumed gas.)

  P2S current  : cost = F_res + gas_used * eff_price
                 (reservation fee F_res = phi*gas_limit*base burned in B1, PLUS the
                  standard EIP-1559 execution fee on gas_used in B2.)

  P2S refund   : cost = F_res
                 (NEW design: on a revealed-but-reverted MT, refund the WHOLE B2
                  execution gas; keep F_res -- it is burned in B1 and is
                  non-refundable. The user who showed up and reverted pays only the
                  reservation fee.)

Key question: under the refund design, do benign reverted users pay MORE or LESS
than on Ethereum today? Ratio_refund = F_res / (gas_used*eff_price). They pay less
whenever F_res < their forfeited gas, i.e. phi*(limit/used) < (base+prio)/base.

Reads the two precomputed datasets (low-fee and congestion) and writes a CDF
figure plus a console table. No network access.
"""
import json
import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import seaborn as sns

# Shared style — matches the other P2S plot scripts (plots/plot_*.py).
FS_LABEL = 24
FS_TICK = 20
FS_LEGEND = 18
_DEEP = sns.color_palette("deep")

# eth_price_usd recorded in each JSON is the CURRENT coin price; the congestion
# window is May 2022, so override its USD with the real contemporaneous price.
DATASETS = {
    "low-fee\n(base ~0.23 gwei)":  ("data/revert_cost_analysis.json", 1754.9),
    "congestion\n(base ~90 gwei)": ("data/revert_cost_highfee.json", 2800.0),
}

COHORTS = {
    "slippage":          lambda r: r["category"] == "slippage",
    "slippage+in-block": lambda r: r["category"] == "slippage"
                                   or (r["category"] == "in_block_state_dependent" and r["is_dex"]),
    "all DEX":           lambda r: r["is_dex"],
    "all reverts":       lambda r: True,
}


def pct(xs, q):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(q * len(xs)))] if xs else float("nan")


def summarize():
    print(f"{'regime':<12}{'cohort':<18}{'n':>5}  "
          f"{'refund ratio (P2S/ETH): med  p90  p99':<38}  "
          f"{'%cheaper':>9}  {'med |Δ| USD (refund)':>22}")
    out = {}
    for label, (path, eth_usd) in DATASETS.items():
        rows = json.load(open(path))["reverted_txs"]
        regime = label.split("\n")[0]
        out[regime] = {}
        for cname, pred in COHORTS.items():
            sub = [r for r in rows
                   if pred(r) and r["cost_today_eth"] and r["f_res_eth"] is not None]
            if not sub:
                continue
            # refund design: pay F_res only -> ratio vs ETH today
            ratios = [r["f_res_eth"] / r["cost_today_eth"] for r in sub]
            cheaper = sum(1 for x in ratios if x < 1.0) / len(ratios)
            # signed delta (refund cost - eth today): negative = user saves
            deltas_usd = [(r["f_res_eth"] - r["cost_today_eth"]) * eth_usd for r in sub]
            med_delta = pct(deltas_usd, 0.5)
            out[regime][cname] = {
                "n": len(sub),
                "ratio_med": pct(ratios, 0.5), "ratio_p90": pct(ratios, 0.9),
                "ratio_p99": pct(ratios, 0.99), "pct_cheaper": cheaper,
                "med_delta_usd": med_delta, "ratios": ratios,
                "old_ratio_med": pct([r["overhead_ratio"] for r in sub], 0.5),
                # absolute per-revert cost (USD) under each system
                "eth_usd_arr":    [r["cost_today_eth"] * eth_usd for r in sub],
                "p2s_refund_arr": [r["f_res_eth"] * eth_usd for r in sub],
                "p2s_naive_arr":  [r["cost_p2s_eth"] * eth_usd for r in sub],
            }
            print(f"{regime:<12}{cname:<18}{len(sub):>5}  "
                  f"{pct(ratios,0.5):>6.2f}{pct(ratios,0.9):>6.2f}{pct(ratios,0.99):>6.2f}"
                  f"{'':>20}{100*cheaper:>8.0f}%  "
                  f"{('saves $%.2f'%-med_delta) if med_delta<0 else ('+$%.2f'%med_delta):>22}")
    return out


def _ecdf(xs):
    xs = sorted(xs)
    return xs, [(i + 1) / len(xs) for i in range(len(xs))]


def plot(out):
    """Two figures (one per fee regime): ECDF of absolute per-revert cost (USD)
    for the slippage cohort, comparing Ethereum today, P2S with the refund
    design (our system), and the naive P2S reserve+gas rule. House style
    (matches plots/plot_welfare.py): one plot per figure, no title, borderless
    legend lower-right."""
    C_POS = _DEEP[3]   # red-orange, baseline (matches plot_welfare.py)
    C_P2S = _DEEP[0]   # steel blue, P2S
    models = [
        ("eth_usd_arr",    "Ethereum",        C_POS,    "-"),
        ("p2s_refund_arr", "P2S (refund)",    C_P2S,    "-"),
        ("p2s_naive_arr",  "P2S (no refund)", _DEEP[7], "--"),
    ]
    panels = [
        ("low-fee",    "revert_refund_lowfee.pdf"),
        ("congestion", "revert_refund_congestion.pdf"),
    ]
    for regime, fname in panels:
        d = out[regime]["slippage"]
        sns.set_theme(style="ticks")
        fig, ax = plt.subplots(figsize=(7, 5))
        for key, label, col, ls in models:
            xs, ys = _ecdf(d[key])
            ax.plot(xs, ys, label=label, color=col, lw=2.2, linestyle=ls)
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
        for base in ["figures", "/Users/tammy/Code/P2S_Overleaf/Figures"]:
            os.makedirs(base, exist_ok=True)
            p = os.path.join(base, fname)
            plt.savefig(p, dpi=300, bbox_inches="tight")
            print("wrote", p)
        plt.close()


if __name__ == "__main__":
    plot(summarize())
