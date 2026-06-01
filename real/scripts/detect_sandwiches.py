#!/usr/bin/env python3
"""Detect REAL historical sandwich attacks on Ethereum from on-chain Swap events
(Uniswap V2 AND V3), following the standard log-based heuristic (cf. Qin et al.,
IEEE S&P 2022; Zhou et al.). Replaces our earlier hypothetical swept victims with
real attacks, as BlindPerm (eprint 2023/1061) grounds its simulation.

Per WETH-paired pool, per block: a sandwich is an attacker X with a WETH-in buy at
log position p, a different victim's WETH-in buy at p<v<q, and X selling back
(WETH out) at q. Profit (ETH) = WETH_out(q) - WETH_in(p). We sample 10-block
windows (free-tier getLogs cap) across ~a year. Every such attack is
content-dependent => P2S survival probability 0 (validated on real EVM by
measure_mev), so the detected total is MEV that P2S eliminates.
"""
import json, os, sys, time, ssl, urllib.request
try:
    import certifi
    _CTX = ssl.create_default_context(cafile=certifi.where())
except Exception:
    _CTX = ssl.create_default_context(); _CTX.check_hostname = False; _CTX.verify_mode = ssl.CERT_NONE

RPC = os.environ.get("P2S_ARCHIVE_RPC") or sys.exit("set $P2S_ARCHIVE_RPC")
WETH = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"
V2_TOPIC = "0xd78ad95fa46c994b6551d0da85fc275fe613ce37657fb8d5e3d130840159d822"
V3_TOPIC = "0xc42079f94a6350d7e6235f29174924f928cc2ac818eb64fed8004e115fbcca67"
WEI = 10**18
SPAN = 10
WINDOWS = 40
STRIDE = 54000   # ~9 days; 40 windows ~= a year of monthly-ish samples
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "sandwiches.json")

_id = 0
def rpc(method, params):
    global _id; _id += 1
    body = json.dumps({"jsonrpc": "2.0", "id": _id, "method": method, "params": params}).encode()
    for a in range(5):
        try:
            req = urllib.request.Request(RPC, data=body, headers={"content-type": "application/json"})
            d = json.load(urllib.request.urlopen(req, timeout=40, context=_CTX))
            if "error" in d:
                raise RuntimeError(d["error"])
            return d["result"]
        except Exception as e:
            if a == 4:
                raise
            time.sleep(1.5 * (a + 1))

def h2i(x): return int(x, 16)
def signed(word):
    v = int(word, 16)
    return v - (1 << 256) if v >= (1 << 255) else v

_widx = {}
def weth_index(pool):
    if pool in _widx:
        return _widx[pool]
    try:
        t0 = rpc("eth_call", [{"to": pool, "data": "0x0dfe1681"}, "latest"])  # token0()
        t1 = rpc("eth_call", [{"to": pool, "data": "0xd21220a7"}, "latest"])  # token1()
    except Exception:
        _widx[pool] = None; return None
    a0 = ("0x" + t0[-40:]).lower() if t0 and len(t0) >= 42 else ""
    a1 = ("0x" + t1[-40:]).lower() if t1 and len(t1) >= 42 else ""
    idx = 0 if a0 == WETH else (1 if a1 == WETH else None)
    _widx[pool] = idx
    return idx

def weth_flow(topic0, data, widx):
    """Return (weth_in, weth_out) in wei for one swap, given which token index is WETH."""
    b = data[2:]
    if topic0 == V2_TOPIC:
        a0In, a1In, a0Out, a1Out = (int(b[i*64:(i+1)*64], 16) for i in range(4))
        if widx == 0:
            return a0In, a0Out
        return a1In, a1Out
    else:  # V3: amount0, amount1 signed (pool perspective: +in to pool, -out of pool)
        amt = signed(b[0:64]) if widx == 0 else signed(b[64:128])
        return (amt, 0) if amt > 0 else (0, -amt)

def get_reserves(pool, block):
    """V2 getReserves() at a given block. Returns (r0, r1) or None."""
    try:
        res = rpc("eth_call", [{"to": pool, "data": "0x0902f1ac"}, hex(block)])
        b = res[2:]
        return int(b[0:64], 16), int(b[64:128], 16)
    except Exception:
        return None

def detect_group(swaps):
    """swaps sorted by logIndex, each {to, win, wout}. Returns tuples
    (attacker, profit_wei, front_weth_in_wei, victim_weth_in_wei)."""
    found = []
    n = len(swaps)
    for p in range(n):
        if swaps[p]["win"] == 0:
            continue
        X = swaps[p]["to"]
        victim = False; victim_max = 0
        for q in range(p+1, n):
            t = swaps[q]
            if t["to"] != X and t["win"] > 0:
                victim = True
                if t["win"] > victim_max:
                    victim_max = t["win"]
            if t["to"] == X and t["wout"] > 0 and victim:
                profit = t["wout"] - swaps[p]["win"]
                if profit > 0:
                    found.append((X, profit, swaps[p]["win"], victim_max))
                break
    return found

def scan_window(lo):
    frm, to = lo - (SPAN - 1), lo
    logs = rpc("eth_getLogs", [{"fromBlock": hex(frm), "toBlock": hex(to),
                                "topics": [[V2_TOPIC, V3_TOPIC]]}])
    # group by (pool, block); keep raw until we know a group is worth resolving
    groups = {}
    for lg in logs:
        if len(lg.get("topics", [])) < 3:
            continue
        key = (lg["address"].lower(), lg["blockNumber"])
        groups.setdefault(key, []).append(lg)
    sandwiches = []
    for (pool, blk), lgs in groups.items():
        if len(lgs) < 3:
            continue
        tos = [lg["topics"][2][-40:].lower() for lg in lgs]
        if len(set(tos)) == len(tos):
            continue  # no repeated recipient -> no attacker straddling; skip (saves token0 calls)
        widx = weth_index(pool)
        if widx is None:
            continue
        version = "v2" if lgs[0]["topics"][0].lower() == V2_TOPIC else "v3"
        swaps = []
        for lg in lgs:
            win, wout = weth_flow(lg["topics"][0].lower(), lg["data"], widx)
            swaps.append({"li": h2i(lg["logIndex"]), "to": lg["topics"][2][-40:].lower(),
                          "win": win, "wout": wout})
        swaps.sort(key=lambda r: r["li"])
        reserves = None  # fetch once per V2 pool/block that has a sandwich
        for X, profit, frontin, vic in detect_group(swaps):
            rec = {"pool": pool, "block": h2i(blk), "version": version, "attacker": "0x"+X,
                   "profit_eth": profit/WEI, "front_weth_in_eth": frontin/WEI,
                   "victim_weth_in_eth": vic/WEI}
            if version == "v2":
                if reserves is None:
                    r = get_reserves(pool, h2i(blk) - 1)
                    reserves = r if r else (0, 0)
                r0, r1 = reserves
                rec["reserve_eth_wei"] = r0 if widx == 0 else r1
                rec["reserve_token"] = r1 if widx == 0 else r0
            sandwiches.append(rec)
    return len(logs), sandwiches

def main():
    head = h2i(rpc("eth_blockNumber", []))
    print(f"head={head}; sampling {WINDOWS} windows x {SPAN} blocks (~{STRIDE} apart), V2+V3", flush=True)
    per_window, total = [], []
    for i in range(WINDOWS):
        lo = head - i * STRIDE
        if lo < 12_500_000:
            break
        try:
            nlogs, sws = scan_window(lo)
        except Exception as e:
            print(f"  @{lo}: ERROR {e}", flush=True); continue
        eth = sum(s["profit_eth"] for s in sws)
        per_window.append({"block": lo, "n_swaps": nlogs, "n_sandwiches": len(sws), "extracted_eth": eth})
        total.extend(sws)
        print(f"  @{lo}: {nlogs} swaps -> {len(sws)} sandwiches, {eth:.4f} ETH", flush=True)
    import statistics as _st
    prof_list = sorted([s["profit_eth"] for s in total], reverse=True)
    summary = {
        "n_windows": len(per_window), "blocks_sampled": len(per_window) * SPAN,
        "n_sandwiches_total": len(total),
        "total_extracted_eth": sum(prof_list),
        "p2s_eliminated_eth": sum(prof_list),
        "mean_per_sandwich_eth": (sum(prof_list)/len(prof_list)) if prof_list else 0,
        "median_per_sandwich_eth": _st.median(prof_list) if prof_list else 0,
        "all_profits_eth": prof_list,
        "windows": per_window,
        "top": sorted(total, key=lambda s: -s["profit_eth"])[:10],
        "all_sandwiches": total,
        # V2 attacked trades usable for the faithful t8n anchor (have reserves + victim size)
        "attacked_trades_v2": [s for s in total
                               if s.get("version") == "v2" and s.get("reserve_eth_wei", 0) > 0
                               and s.get("victim_weth_in_eth", 0) > 0],
    }
    json.dump(summary, open(OUT, "w"), indent=2)
    print(f"\nTOTAL: {len(total)} real sandwiches over {len(per_window)*SPAN} blocks, "
          f"{summary['total_extracted_eth']:.4f} ETH; mean {summary['mean_per_sandwich_eth']:.5f} ETH", flush=True)
    print(f"P2S eliminates (content-dependent, survival prob 0): {summary['p2s_eliminated_eth']:.4f} ETH")
    print(f"wrote {OUT}")

if __name__ == "__main__":
    main()
