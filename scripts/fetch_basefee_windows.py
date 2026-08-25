#!/usr/bin/env python3
"""Sample real mainnet base fees across a year, via eth_feeHistory.

The simulator's block cache (data/ethereum_blocks_cache.json, heights
18,748,996-18,750,000) is a single ~3.4 h window from Dec 2023, before Dencun.
This script pulls 1024-block windows spread over the past year so the paper can
state the base-fee regime its reservation-fee thresholds are actually deployed
into, rather than extrapolating from one pre-Dencun window.

feeHistory needs only block headers, so any archive-serving endpoint works.
Writes data/basefee_windows.json.

Usage:  python scripts/fetch_basefee_windows.py
"""
import json, os, ssl, statistics, sys, time, urllib.request
from datetime import datetime, timezone

ENDPOINTS = ["https://eth.drpc.org", "https://rpc.flashbots.net",
             "https://ethereum-rpc.publicnode.com"]
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data",
                   "basefee_windows.json")
_CTX = ssl.create_default_context(cafile="/etc/ssl/cert.pem")
BLOCKS_PER_DAY = 7200            # 12 s slots
WINDOW = 1024                    # feeHistory maximum
DAYS_BACK = [0, 15, 30, 45, 60, 90, 120, 150, 180, 240, 300, 360]


def rpc(method, params, tries=2):
    last = None
    for url in ENDPOINTS:
        for _ in range(tries):
            try:
                body = json.dumps({"jsonrpc": "2.0", "id": 1,
                                   "method": method, "params": params}).encode()
                req = urllib.request.Request(url, data=body, headers={
                    "content-type": "application/json", "User-Agent": "Mozilla/5.0"})
                r = json.load(urllib.request.urlopen(req, timeout=25, context=_CTX))
                if r.get("result") is not None:
                    return r["result"]
                last = r.get("error")
            except Exception as e:
                last = e
            time.sleep(1.0)
    raise RuntimeError(f"all endpoints failed for {method}: {last}")


def main():
    head = int(rpc("eth_getBlockByNumber", ["latest", False])["number"], 16)
    windows, pooled = [], []
    for d in DAYS_BACK:
        end = head - d * BLOCKS_PER_DAY
        fh = rpc("eth_feeHistory", [hex(WINDOW), hex(end), []])
        # feeHistory returns blockCount+1 entries; the last is the next block's
        # base fee, which is not part of the sampled window.
        bf = [int(x, 16) / 1e9 for x in fh["baseFeePerGas"][:-1]]
        oldest = int(fh["oldestBlock"], 16)
        hdr = rpc("eth_getBlockByNumber", [hex(oldest), False])
        ts = int(hdr["timestamp"], 16)
        gas_limit = int(hdr["gasLimit"], 16)
        rec = {
            "days_back": d, "oldest_block": oldest, "newest_block": end,
            "date_utc": datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d"),
            "gas_limit": gas_limit, "n": len(bf),
            "min": min(bf), "median": statistics.median(bf), "max": max(bf),
            "base_fees_gwei": bf,
        }
        windows.append(rec); pooled += bf
        print(f"{rec['date_utc']}  blocks {oldest}-{end}  n={len(bf):4d}  "
              f"gasLimit={gas_limit/1e6:.0f}M  min={min(bf):8.4f}  "
              f"p50={statistics.median(bf):8.4f}  max={max(bf):9.4f} gwei", flush=True)
        time.sleep(0.5)

    pooled.sort()
    q = lambda p: pooled[int(p * (len(pooled) - 1))]
    summary = {
        "n": len(pooled), "p05": q(.05), "p25": q(.25), "p50": q(.50),
        "p75": q(.75), "p95": q(.95), "max": pooled[-1],
        "frac_below_20_gwei": sum(1 for x in pooled if x < 20) / len(pooled),
        "frac_below_5_gwei":  sum(1 for x in pooled if x < 5) / len(pooled),
        "frac_below_1_gwei":  sum(1 for x in pooled if x < 1) / len(pooled),
    }
    print("\nPOOLED over %d blocks: p05=%.4f p25=%.4f p50=%.4f p75=%.4f p95=%.4f max=%.2f gwei"
          % (summary["n"], summary["p05"], summary["p25"], summary["p50"],
             summary["p75"], summary["p95"], summary["max"]))
    print("below 20 gwei: %.2f%%   below 5 gwei: %.2f%%   below 1 gwei: %.2f%%"
          % (100*summary["frac_below_20_gwei"], 100*summary["frac_below_5_gwei"],
             100*summary["frac_below_1_gwei"]))
    json.dump({"head": head, "fetched_utc": datetime.now(timezone.utc).isoformat(),
               "summary": summary, "windows": windows}, open(OUT, "w"))
    print("wrote", os.path.normpath(OUT))


if __name__ == "__main__":
    sys.exit(main())
