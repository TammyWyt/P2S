#!/usr/bin/env python3
"""M5: measured sandwich-MEV reduction of P2S vs PoS on real mainnet swaps.

For each of the 50 real fixtures (real V2 pool reserves + real victim swap size),
we deploy a Uniswap-V2-faithful constant-product pool (MiniAMM, 0.3% fee), size
the attacker's front-run to maximize profit (exact V2 integer math), then EXECUTE
both orderings through `evm t8n` on real EVM state:

  PoS arm : [attacker.buy(F), victim.buy(V), attacker.sell(atk_tokens)]  (sandwich)
  P2S arm : [attacker.buy(F), attacker.sell(atk_tokens), victim.buy(V)]  (blind: forced adjacent)

The attacker's extractable MEV is the measured ETH balance delta (a rational
attacker only executes if >0, so P2S extractable MEV floors at 0). Aggregate over
fixtures gives the measured reduction -- the honest replacement for the old
simulated 97.8% headline.
"""
import json, subprocess, tempfile, os, sys, glob, re

EVM = os.environ.get("EVM", "/opt/homebrew/bin/evm")
SOLC = os.environ.get("SOLC", "/opt/homebrew/bin/solc")
HERE = os.path.dirname(os.path.abspath(__file__))
SPIKE = os.path.join(HERE, "..", "proto", "spike")
WL = os.path.join(HERE, "..", "data", "workload")
WEI = 10**18

DEPLOYER = ("0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266", "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80")
ATTACKER = ("0x70997970C51812dc3A010C7d01b50e0d17dc79C8", "0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d")
VICTIM   = ("0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC", "0x5de4111afa1a4b94908f83103eb1f1706367c2e68ca870fc3fb9a804cdab365a")
SEL_BUY, SEL_SELL = "a6f2ae3a", "e4849b32"
GAS_PRICE = "0x3b9aca00"
SIG = {"v": "0x0", "r": "0x0", "s": "0x0"}
ENV = {"currentCoinbase": "0x" + "00"*20, "currentGasLimit": "0x7fffffffffffffff",
       "currentNumber": "0x1", "currentTimestamp": "0x3e8", "currentBaseFee": "0x1",
       "currentRandom": "0x" + "00"*32, "withdrawals": []}
FUND = hex(2_000_000 * WEI)

def compile_amm():
    out = subprocess.run([SOLC, "--bin", "--optimize", os.path.join(SPIKE, "MiniAMM.sol")],
                         capture_output=True, text=True)
    if out.returncode != 0:
        sys.exit(out.stderr)
    return re.search(r"Binary:\s*\n([0-9a-fA-F]+)", out.stdout).group(1)

def u256(n): return f"{n:064x}"

def t8n(alloc, txs):
    d = tempfile.mkdtemp(prefix="t8n_m5_")
    for nm, ob in (("a.json", alloc), ("e.json", ENV), ("t.json", txs)):
        with open(os.path.join(d, nm), "w") as f: json.dump(ob, f)
    cmd = [EVM, "t8n", "--input.alloc", os.path.join(d,"a.json"), "--input.env", os.path.join(d,"e.json"),
           "--input.txs", os.path.join(d,"t.json"), "--output.basedir", d,
           "--output.alloc", "oa.json", "--output.result", "or.json",
           "--state.fork", "Shanghai", "--state.chainid", "1"]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        sys.exit(f"t8n failed: {p.stderr}")
    with open(os.path.join(d,"oa.json")) as f: oa = json.load(f)
    with open(os.path.join(d,"or.json")) as f: orr = json.load(f)
    return oa, orr

def bal(alloc, addr):
    r = alloc.get(addr.lower()) or alloc.get(addr) or {}
    return int(r.get("balance", "0x0"), 16)

def amt_out(ain, rin, rout):   # exact Uniswap V2 getAmountOut (integer)
    aif = ain * 997
    return (aif * rout) // (rin * 1000 + aif)

def sandwich_profit(Re, Rt, F, V):
    tok = amt_out(F, Re, Rt)
    Re1, Rt1 = Re + F, Rt - tok
    tok_v = amt_out(V, Re1, Rt1)
    Re2, Rt2 = Re1 + V, Rt1 - tok_v
    back = amt_out(tok, Rt2, Re2)
    return back - F, tok

def optimal_front(Re, Rt, V, cap):
    # coarse-to-fine search for profit-maximizing front-run F
    best_F, best_p = 0, 0
    lo, hi = 10**15, min(cap, Re // 2)
    for _ in range(6):
        step = max((hi - lo) // 40, 1)
        F = lo
        while F <= hi:
            p, _t = sandwich_profit(Re, Rt, F, V)
            if p > best_p:
                best_p, best_F = p, F
            F += step
        lo, hi = max(10**15, best_F - step), best_F + step
    return best_F, best_p

def run():
    creation = compile_amm()
    files = sorted(glob.glob(os.path.join(WL, "slot_*.json")))
    results = []
    pos_total = p2s_total = 0.0
    for fpath in files:
        fx = json.load(open(fpath))
        Re, Rt, V = fx["reserve_eth_wei"], fx["reserve_token"], fx["victim_weth_in_wei"]

        # deploy pool with the real reserves
        dalloc = {a[0]: {"balance": FUND, "nonce": "0x0"} for a in (DEPLOYER, ATTACKER, VICTIM)}
        dtx = {"input": "0x"+creation+u256(Rt), "gas": "0x400000", "gasPrice": GAS_PRICE,
               "nonce": "0x0", "value": hex(Re), "secretKey": DEPLOYER[1], "chainId":"0x1", "to":None, **SIG}
        post, dres = t8n(dalloc, [dtx])
        pool = dres["receipts"][0]["contractAddress"]

        F, analytic = optimal_front(Re, Rt, V, cap=500*WEI)
        atk_tokens = amt_out(F, Re, Rt)

        def buy(acct, n, amt): return {"input":"0x"+SEL_BUY,"gas":"0x200000","gasPrice":GAS_PRICE,"nonce":hex(n),"value":hex(amt),"to":pool,"secretKey":acct[1],"chainId":"0x1",**SIG}
        def sell(acct, n, amt): return {"input":"0x"+SEL_SELL+u256(amt),"gas":"0x200000","gasPrice":GAS_PRICE,"nonce":hex(n),"value":"0x0","to":pool,"secretKey":acct[1],"chainId":"0x1",**SIG}

        atk0 = bal(post, ATTACKER[0])
        pos_alloc, _ = t8n(post, [buy(ATTACKER,0,F), buy(VICTIM,0,V), sell(ATTACKER,1,atk_tokens)])
        p2s_alloc, _ = t8n(post, [buy(ATTACKER,0,F), sell(ATTACKER,1,atk_tokens), buy(VICTIM,0,V)])
        pos_mev = (bal(pos_alloc, ATTACKER[0]) - atk0) / WEI
        p2s_mev = (bal(p2s_alloc, ATTACKER[0]) - atk0) / WEI
        pos_ext = max(0.0, pos_mev)        # rational attacker only acts if profitable
        p2s_ext = max(0.0, p2s_mev)
        pos_total += pos_ext
        p2s_total += p2s_ext
        results.append({"fixture": os.path.basename(fpath), "pool": fx["pool_name"],
                        "victim_weth": V/WEI, "front_run_eth": F/WEI,
                        "pos_mev_eth": pos_mev, "p2s_mev_eth": p2s_mev,
                        "analytic_profit_eth": analytic/WEI})
        print(f"{fx['pool_name']:10s} blk {fx['block']} V={V/WEI:.3f} F={F/WEI:.3f}  "
              f"PoS_MEV={pos_mev:+.5f}  P2S_MEV={p2s_mev:+.5f} ETH", flush=True)

    red = 100.0 * (1 - p2s_total / pos_total) if pos_total > 0 else float("nan")
    summary = {"n": len(results), "pos_total_mev_eth": pos_total, "p2s_total_mev_eth": p2s_total,
               "reduction_pct": red, "per_fixture": results}
    out = os.path.join(HERE, "..", "data", "mev_measured.json")
    json.dump(summary, open(out, "w"), indent=2)
    print(f"\n==== MEASURED over {len(results)} real swaps ====")
    print(f"PoS extractable sandwich MEV : {pos_total:.4f} ETH")
    print(f"P2S extractable sandwich MEV : {p2s_total:.4f} ETH")
    print(f"Reduction                    : {red:.2f}%")
    print(f"wrote {out}")

if __name__ == "__main__":
    run()
