#!/usr/bin/env python3
"""Ethereum mainnet block extractor via JSON-RPC eth_getBlockByNumber.

Pulls N consecutive mainnet blocks (full transactions) from a public JSON-RPC
node and writes them to data/ethereum_blocks_cache.json in the schema the
simulator consumes. One request per block (no pagination), which is faster and
more reliable than the Blockscout REST path in extract_ethereum_blocks.py.

Usage:
    python scripts/extract_blocks_rpc.py [num_blocks] [end_block]

stdlib only (urllib); macOS framework Python needs cafile=/etc/ssl/cert.pem.
"""
import json, os, ssl, sys, time, urllib.request
from datetime import datetime, timezone

RPC = os.environ.get("P2S_RPC", "https://ethereum-rpc.publicnode.com")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "ethereum_blocks_cache.json")
_CTX = ssl.create_default_context(cafile="/etc/ssl/cert.pem")
_UA = {"content-type": "application/json", "User-Agent": "Mozilla/5.0 (P2S-research)"}


def _rpc(method, params, retries=4):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    for a in range(retries):
        try:
            req = urllib.request.Request(RPC, data=body, headers=_UA)
            d = json.load(urllib.request.urlopen(req, timeout=30, context=_CTX))
            if "result" in d and d["result"] is not None:
                return d["result"]
        except Exception as e:
            time.sleep(0.5 * (a + 1))
    return None


def _block(n):
    b = _rpc("eth_getBlockByNumber", [hex(n), True])
    if not b:
        return None
    ts = int(b["timestamp"], 16)
    txs = [{
        "hash": t.get("hash", ""),
        "from": t.get("from", "") or "",
        "to": t.get("to", "") or "",
        "value": int(t.get("value", "0x0"), 16),
        "gas": int(t.get("gas", "0x0"), 16),
        "gasPrice": int(t.get("gasPrice", "0x0"), 16),
        "nonce": int(t.get("nonce", "0x0"), 16),
        "timestamp": ts,
    } for t in b.get("transactions", [])]
    return {
        "block_number": int(b["number"], 16),
        "timestamp": ts,
        "transaction_count": len(txs),
        "block_size": int(b.get("size", "0x0"), 16),
        "base_fee": int(b.get("baseFeePerGas", "0x0"), 16),
        "gas_used": int(b.get("gasUsed", "0x0"), 16),
        "gas_limit": int(b.get("gasLimit", "0x0"), 16),
        "transactions": txs,
    }


def main():
    num = int(sys.argv[1]) if len(sys.argv) > 1 else 1005
    end = int(sys.argv[2]) if len(sys.argv) > 2 else 18_750_000
    cache, failures = {}, 0
    for i in range(num):
        n = end - i
        blk = _block(n)
        if blk is None:
            failures += 1
            continue
        cache[str(n)] = blk
        if (i + 1) % 100 == 0:
            print(f"  fetched {i+1}/{num} (failures {failures})", flush=True)
    cache["_meta"] = {
        "block_range": [end - num + 1, end],
        "retrieval_date": datetime.now(timezone.utc).isoformat(),
        "source": RPC,
        "method": "eth_getBlockByNumber",
        "num_blocks": len(cache) - 0,
    }
    with open(OUT, "w") as f:
        json.dump(cache, f)
    print(f"wrote {len(cache)-1} blocks + _meta to {OUT} (failures {failures})", flush=True)


if __name__ == "__main__":
    main()
