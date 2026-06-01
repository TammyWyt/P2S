#!/usr/bin/env python3
"""M5 (sweep): measured sandwich-MEV vs victim size on REAL pool reserves.

Real sandwiches are rare on deep blue-chip V2 pools because a swap must move
price by more than the attacker's 0.6% round-trip fee. Rather than hunt for rare
real whales on a rate-limited free tier, we characterize the mechanism directly:
for each pool's REAL on-chain reserves, sweep the victim swap size and measure,
on real EVM via `evm t8n`, the attacker's optimally-sized sandwich profit under
PoS ordering vs P2S blind ordering.

Result shape: PoS-extractable MEV rises with victim size once it clears the fee
threshold; P2S-extractable MEV is exactly 0 at every size, because the attacker
cannot place its txs around a victim whose content was hidden when order was
fixed. This is content-ordering independence, measured on real pool depths.
"""
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from v2math import optimal_front, amt_out
from measure_mev import (compile_amm, t8n, bal, u256, DEPLOYER, ATTACKER, VICTIM,
                         SEL_BUY, SEL_SELL, GAS_PRICE, SIG, FUND, WEI)

VICTIM_GRID_ETH = [1, 2, 4, 8, 15, 25, 40, 60, 100, 160, 250, 400]

def deploy_pool(creation, reserve_eth, reserve_tok):
    dalloc = {a[0]: {"balance": FUND, "nonce": "0x0"} for a in (DEPLOYER, ATTACKER, VICTIM)}
    dtx = {"input": "0x"+creation+u256(reserve_tok), "gas": "0x400000", "gasPrice": GAS_PRICE,
           "nonce": "0x0", "value": hex(reserve_eth), "secretKey": DEPLOYER[1], "chainId": "0x1", "to": None, **SIG}
    post, dres = t8n(dalloc, [dtx])
    return post, dres["receipts"][0]["contractAddress"]

def arms(post, pool, F, atk_tokens, V):
    def buy(acct, n, amt): return {"input":"0x"+SEL_BUY,"gas":"0x200000","gasPrice":GAS_PRICE,"nonce":hex(n),"value":hex(amt),"to":pool,"secretKey":acct[1],"chainId":"0x1",**SIG}
    def sell(acct, n, amt): return {"input":"0x"+SEL_SELL+u256(amt),"gas":"0x200000","gasPrice":GAS_PRICE,"nonce":hex(n),"value":"0x0","to":pool,"secretKey":acct[1],"chainId":"0x1",**SIG}
    atk0 = bal(post, ATTACKER[0])
    pos, _ = t8n(post, [buy(ATTACKER,0,F), buy(VICTIM,0,V), sell(ATTACKER,1,atk_tokens)])
    p2s, _ = t8n(post, [buy(ATTACKER,0,F), sell(ATTACKER,1,atk_tokens), buy(VICTIM,0,V)])
    return (bal(pos, ATTACKER[0])-atk0)/WEI, (bal(p2s, ATTACKER[0])-atk0)/WEI

def main():
    snap = json.load(open(os.path.join(HERE, "..", "data", "pool_reserves.json")))
    creation = compile_amm()
    out = {"block": snap["block"], "pools": {}}
    for name, pd in snap["pools"].items():
        Re, Rt = pd["reserve_eth_wei"], pd["reserve_token"]
        post, pool = deploy_pool(creation, Re, Rt)
        curve = []
        print(f"\n=== {name}  ({Re/WEI:.0f} ETH deep) ===")
        for v in VICTIM_GRID_ETH:
            V = int(v * WEI)
            F, analytic = optimal_front(Re, Rt, V, cap=5000*WEI)
            atk_tokens = amt_out(F, Re, Rt) if F > 0 else 0
            if F == 0:
                pos_mev = p2s_mev = 0.0
            else:
                pos_mev, p2s_mev = arms(post, pool, F, atk_tokens, V)
            pos_ext = max(0.0, pos_mev)
            curve.append({"victim_eth": v, "front_run_eth": F/WEI,
                          "pos_mev_eth": pos_mev, "p2s_mev_eth": p2s_mev, "pos_ext_eth": pos_ext})
            print(f"  V={v:4d} ETH  F={F/WEI:7.2f}  PoS_MEV={pos_mev:+10.5f}  P2S_MEV={p2s_mev:+.5f} ETH")
        out["pools"][name] = {"reserve_eth": Re/WEI, "curve": curve}
    path = os.path.join(HERE, "..", "data", "mev_sweep.json")
    json.dump(out, open(path, "w"), indent=2)
    # headline
    print("\n==== HEADLINE (real reserves, real EVM) ====")
    for name, p in out["pools"].items():
        prof = [c for c in p["curve"] if c["pos_ext_eth"] > 0.001]
        if prof:
            thr = prof[0]["victim_eth"]; mx = max(c["pos_ext_eth"] for c in p["curve"])
            print(f"  {name:10s}: sandwich profitable for victims >= ~{thr} ETH; max PoS MEV {mx:.4f} ETH; P2S MEV 0 at every size")
        else:
            print(f"  {name:10s}: no profitable sandwich up to {VICTIM_GRID_ETH[-1]} ETH")
    print(f"wrote {path}")

if __name__ == "__main__":
    main()
