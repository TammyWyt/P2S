#!/usr/bin/env python3
"""M2: build a real-mainnet workload of sandwichable Uniswap V2 swaps.

Because the bundled cache is not real L1 data (its tx hashes do not resolve on
mainnet) and the free-tier RPC gates `prestateTracer`, we take the documented
fallback: sample REAL recent mainnet swaps and the REAL pool reserves just
before each, then (in M5) replay them against a constant-product pool calibrated
to those reserves with Uniswap V2's 0.3% fee. Uniswap V2 *is* x*y=k with a 0.3%
fee, so this is faithful for sandwich MEV while staying within free-tier methods
(eth_getLogs / eth_call). Upgrade path: a paid tier unlocks prestateTracer and
the exact pool bytecode.

Output: data/workload/slot_<block>_<logIndex>.json fixtures + an index file.
RPC endpoint is read from $P2S_ARCHIVE_RPC (never hardcoded).
"""
import json, os, sys, time, ssl, urllib.request
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from v2math import optimal_front

try:
    import certifi
    _CTX = ssl.create_default_context(cafile=certifi.where())
except Exception:
    _CTX = ssl.create_default_context()
    _CTX.check_hostname = False
    _CTX.verify_mode = ssl.CERT_NONE

RPC = os.environ.get("P2S_ARCHIVE_RPC")
if not RPC:
    sys.exit("set $P2S_ARCHIVE_RPC (see .env.local)")

OUT = os.path.join(os.path.dirname(__file__), "..", "..", "data", "workload")
OUT = os.path.abspath(OUT)
os.makedirs(OUT, exist_ok=True)

WETH = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"
# high-liquidity Uniswap V2 pools: addr -> (token0, token1) with which side is WETH
POOLS = {
    "0xB4e16d0168e52d35CaCD2c6185b44281Ec28C9Dc": {"name": "USDC/WETH", "weth": "token1"},
    "0x0d4a11d5EEaaC28EC3F61d100daF4d40471f1852": {"name": "WETH/USDT", "weth": "token0"},
    "0xA478c2975Ab1Ea89e8196811F51A7B7Ade33eB11": {"name": "DAI/WETH",  "weth": "token1"},
}
SWAP_TOPIC = "0xd78ad95fa46c994b6551d0da85fc275fe613ce37657fb8d5e3d130840159d822"
WEI = 10**18
MIN_VICTIM_WETH = 8 * WEI      # whale pre-filter: only swaps big enough to plausibly
                               # beat the 0.6% round-trip fee on these deep pools
MIN_PROFIT_WEI = int(0.005 * WEI)  # keep only swaps with a genuinely profitable sandwich
TARGET = 40                    # number of fixtures to collect
SPAN = 10                      # free-tier eth_getLogs is capped at a 10-block range
MAX_WINDOWS = 1200             # bound total RPC work (<= 12000 blocks scanned)

_id = 0
def rpc(method, params):
    global _id; _id += 1
    body = json.dumps({"jsonrpc": "2.0", "id": _id, "method": method, "params": params}).encode()
    for attempt in range(5):
        try:
            req = urllib.request.Request(RPC, data=body, headers={"content-type": "application/json"})
            with urllib.request.urlopen(req, timeout=30, context=_CTX) as r:
                d = json.load(r)
            if "error" in d:
                raise RuntimeError(d["error"])
            return d["result"]
        except Exception as e:
            if attempt == 4:
                raise
            time.sleep(1.5 * (attempt + 1))

def h2i(x):
    return int(x, 16)

def decode_swap(data):
    b = data[2:]
    vals = [int(b[i*64:(i+1)*64], 16) for i in range(4)]
    return {"amount0In": vals[0], "amount1In": vals[1], "amount0Out": vals[2], "amount1Out": vals[3]}

def get_reserves(pool, block):
    res = rpc("eth_call", [{"to": pool, "data": "0x0902f1ac"}, hex(block)])
    b = res[2:]
    r0 = int(b[0:64], 16)
    r1 = int(b[64:128], 16)
    return r0, r1

def main():
    head = h2i(rpc("eth_blockNumber", []))
    print(f"mainnet head = {head}")
    fixtures = []
    lo = head - 1        # start just below head, walk backwards
    windows = 0
    while len(fixtures) < TARGET and windows < MAX_WINDOWS:
        windows += 1
        frm, to = lo - (SPAN - 1), lo
        lo -= SPAN
        time.sleep(0.05)   # gentle pacing for free-tier rate limits
        for pool, meta in POOLS.items():
            if len(fixtures) >= TARGET:
                break
            try:
                logs = rpc("eth_getLogs", [{"fromBlock": hex(frm), "toBlock": hex(to),
                                            "address": pool, "topics": [SWAP_TOPIC]}])
            except Exception as e:
                print(f"  getLogs {meta['name']} {frm}-{to} failed: {e}")
                continue
            weth_is0 = meta["weth"] == "token0"
            for lg in logs:
                if len(fixtures) >= TARGET:
                    break
                s = decode_swap(lg["data"])
                # victim = someone selling WETH INTO the pool (buying the token) -> classic target
                weth_in = s["amount0In"] if weth_is0 else s["amount1In"]
                if weth_in < MIN_VICTIM_WETH:
                    continue
                blk = h2i(lg["blockNumber"])
                try:
                    r0, r1 = get_reserves(pool, blk - 1)   # reserves at start of victim's block
                except Exception as e:
                    continue
                reserve_eth = r0 if weth_is0 else r1
                reserve_tok = r1 if weth_is0 else r0
                if reserve_eth == 0 or reserve_tok == 0:
                    continue
                # keep only swaps that are ACTUALLY sandwichable on the real reserves
                F, profit = optimal_front(reserve_eth, reserve_tok, weth_in, cap=500 * WEI)
                if profit < MIN_PROFIT_WEI:
                    continue
                fx = {
                    "pool": pool, "pool_name": meta["name"], "block": blk,
                    "log_index": h2i(lg["logIndex"]),
                    "reserve_eth_wei": reserve_eth, "reserve_token": reserve_tok,
                    "victim_weth_in_wei": weth_in, "fee_bps": 30,
                    "front_run_wei": F, "analytic_profit_wei": profit,
                }
                fixtures.append(fx)
                fn = os.path.join(OUT, f"slot_{blk}_{fx['log_index']}.json")
                with open(fn, "w") as f:
                    json.dump(fx, f, indent=2)
                print(f"  [{len(fixtures):2d}] {meta['name']} blk {blk} victim {weth_in/WEI:.2f} WETH "
                      f"pool {reserve_eth/WEI:.0f} ETH  -> sandwich F={F/WEI:.2f} profit={profit/WEI:.4f} ETH",
                      flush=True)
    idx = os.path.join(OUT, "index.json")
    with open(idx, "w") as f:
        json.dump({"count": len(fixtures),
                   "fixtures": [f"slot_{x['block']}_{x['log_index']}.json" for x in fixtures]}, f, indent=2)
    print(f"\nwrote {len(fixtures)} fixtures to {OUT}")

if __name__ == "__main__":
    main()
