#!/usr/bin/env python3
"""GATE / D1 validation (per SIM_SPEC.md): replay the REAL detected sandwich
attacks through real-EVM execution (evm t8n) on a constant-product pool
calibrated to each attack's REAL on-chain reserves, victim size, and the
attacker's REAL front-run size. Checks that t8n reproduces the detected on-chain
profit (model-vs-reality agreement), and that under P2S blind ordering a rational
attacker nets 0.

This replaces the discarded NaN anchor (mev_measured.json), which sampled random
sub-threshold swaps on DEEP pools. Real sandwiches happen on SHALLOW pools where
small victims move price past the fee threshold.
"""
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from v2math import amt_out, sandwich_profit
from measure_mev import (compile_amm, t8n, bal, u256, DEPLOYER, ATTACKER, VICTIM,
                         SEL_BUY, SEL_SELL, GAS_PRICE, SIG, FUND, WEI)

def deploy(creation, Re, Rt):
    alloc = {a[0]: {"balance": FUND, "nonce": "0x0"} for a in (DEPLOYER, ATTACKER, VICTIM)}
    dtx = {"input": "0x"+creation+u256(Rt), "gas": "0x400000", "gasPrice": GAS_PRICE,
           "nonce": "0x0", "value": hex(Re), "secretKey": DEPLOYER[1], "chainId": "0x1", "to": None, **SIG}
    post, dres = t8n(alloc, [dtx])
    return post, dres["receipts"][0]["contractAddress"]

def buy(acct, n, amt, pool):
    return {"input": "0x"+SEL_BUY, "gas": "0x200000", "gasPrice": GAS_PRICE, "nonce": hex(n),
            "value": hex(amt), "to": pool, "secretKey": acct[1], "chainId": "0x1", **SIG}
def sell(acct, n, amt, pool):
    return {"input": "0x"+SEL_SELL+u256(amt), "gas": "0x200000", "gasPrice": GAS_PRICE, "nonce": hex(n),
            "value": "0x0", "to": pool, "secretKey": acct[1], "chainId": "0x1", **SIG}

def main():
    d = json.load(open(os.path.join(HERE, "..", "data", "sandwiches.json")))
    trades = d["attacked_trades_v2"]
    creation = compile_amm()
    rows = []
    pos_total = detected_total = 0.0
    for tr in trades:
        Re, Rt = int(tr["reserve_eth_wei"]), int(tr["reserve_token"])
        F = int(tr["front_weth_in_eth"] * WEI)
        V = int(tr["victim_weth_in_eth"] * WEI)
        if F == 0 or V == 0 or Re == 0 or Rt == 0:
            continue
        post, pool = deploy(creation, Re, Rt)
        atk0 = bal(post, ATTACKER[0])
        atk_tokens = amt_out(F, Re, Rt)
        # PoS arm: replay the REAL sandwich (attacker front, victim, attacker back)
        pos_alloc, _ = t8n(post, [buy(ATTACKER, 0, F, pool), buy(VICTIM, 0, V, pool),
                                  sell(ATTACKER, 1, atk_tokens, pool)])
        repro = (bal(pos_alloc, ATTACKER[0]) - atk0) / WEI
        # P2S arm: order fixed blind -> attacker's two legs forced adjacent, victim cannot be straddled.
        p2s_alloc, _ = t8n(post, [buy(ATTACKER, 0, F, pool), sell(ATTACKER, 1, atk_tokens, pool),
                                  buy(VICTIM, 0, V, pool)])
        p2s_blind = (bal(p2s_alloc, ATTACKER[0]) - atk0) / WEI
        p2s_rational = max(0.0, p2s_blind)   # rational attacker won't submit a losing sandwich
        pos_ext = max(0.0, repro)
        pos_total += pos_ext
        detected_total += tr["profit_eth"]
        rows.append({"pool": tr["pool"], "reserve_eth": Re/WEI, "victim_eth": V/WEI,
                     "front_eth": F/WEI, "detected_profit_eth": tr["profit_eth"],
                     "t8n_pos_profit_eth": repro, "p2s_blind_eth": p2s_blind,
                     "p2s_rational_eth": p2s_rational})
    # agreement between t8n-reproduced and detected (where both > dust)
    pairs = [(r["detected_profit_eth"], r["t8n_pos_profit_eth"]) for r in rows
             if r["detected_profit_eth"] > 1e-4 and r["t8n_pos_profit_eth"] > 1e-4]
    out = {
        "n_trades": len(rows),
        "pos_total_extractable_eth": pos_total,
        "p2s_total_extractable_eth": sum(r["p2s_rational_eth"] for r in rows),
        "detected_total_eth": detected_total,
        "n_validation_pairs": len(pairs),
        "rows": rows,
    }
    json.dump(out, open(os.path.join(HERE, "..", "data", "anchor_t8n.json"), "w"), indent=2)
    print(f"replayed {len(rows)} REAL V2 sandwiches through real-EVM (evm t8n)")
    print(f"  PoS extractable (t8n)  : {pos_total:.4f} ETH")
    print(f"  P2S extractable (rational): {out['p2s_total_extractable_eth']:.4f} ETH")
    print(f"  detected on-chain total: {detected_total:.4f} ETH")
    if pairs:
        import statistics as st
        ratios = [t/dch for dch, t in pairs]
        print(f"  model-vs-reality agreement on {len(pairs)} attacks: "
              f"median t8n/detected ratio = {st.median(ratios):.2f} (1.0 = perfect)")
    red = 100*(1 - out['p2s_total_extractable_eth']/pos_total) if pos_total > 0 else float('nan')
    print(f"  P2S reduction of extractable in-slot sandwich MEV: {red:.1f}%")
    print("wrote real/data/anchor_t8n.json")

if __name__ == "__main__":
    main()
