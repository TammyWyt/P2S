#!/usr/bin/env python3
"""
Ethereum mainnet block extractor — Blockscout REST API.

Pulls ~1000 consecutive Ethereum mainnet blocks via the public Blockscout v2
REST endpoint and writes them to data/ethereum_blocks_cache.json.

Endpoint:
    GET https://eth.blockscout.com/api/v2/blocks/<block_number>
    GET https://eth.blockscout.com/api/v2/blocks/<block_number>/transactions

Output schema (mirrors what scripts/simulation/simulator.py already consumes):

    {
        "<block_number>": {
            "block_number":      int,
            "timestamp":         int      (unix seconds),
            "transaction_count": int,
            "block_size":        int,
            "base_fee":          int      (wei),
            "gas_used":          int,
            "gas_limit":         int,
            "transactions": [{"hash", "from", "to", "value", "gas",
                              "gasPrice", "nonce", "timestamp"}, ...]
        },
        ...
        "_meta": {
            "block_range":     [low, high],
            "retrieval_date":  ISO-8601 timestamp,
            "source_url":      "https://eth.blockscout.com/api/v2",
            "eth_price_usd":   2300.0,   # snapshot at retrieval; can be stale
            "num_blocks":      1000
        }
    }

This script is *not required* to reproduce the figures in the current paper —
the existing data/ethereum_blocks_cache.json is shipped pre-populated.  The
script is included so a reviewer who deletes the cache (or starts from a clean
clone) can regenerate it.

Usage:
    python scripts/extract_ethereum_blocks.py [num_blocks] [start_block]

If start_block is omitted, the latest finalized mainnet block is used.
Rate limit: 5 req/s (Blockscout public tier).  1000 blocks ≈ ~7 minutes.
"""

import json
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests

BLOCKSCOUT_BASE = "https://eth.blockscout.com/api/v2"
DEFAULT_OUT_PATH = "data/ethereum_blocks_cache.json"
DEFAULT_NUM_BLOCKS = 1000
DEFAULT_RATE_DELAY_S = 0.2     # 5 req/s
ETH_PRICE_FALLBACK_USD = 2300.0


def _get_json(url: str, params: Optional[Dict[str, Any]] = None,
              timeout: int = 30, retries: int = 3) -> Optional[Dict[str, Any]]:
    """GET with simple backoff; returns parsed JSON or None on failure."""
    for attempt in range(retries):
        try:
            resp = requests.get(url, params=params, timeout=timeout)
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code == 429:        # rate limit
                time.sleep(2 ** attempt)
                continue
            print(f"  HTTP {resp.status_code}: {url}", file=sys.stderr)
        except requests.RequestException as e:
            print(f"  request error: {e}", file=sys.stderr)
            time.sleep(2 ** attempt)
    return None


def _get_latest_block_number() -> int:
    """Fetch the most recently mined mainnet block number from Blockscout."""
    data = _get_json(f"{BLOCKSCOUT_BASE}/blocks", params={"type": "block"})
    if data and data.get("items"):
        return int(data["items"][0]["height"])
    raise RuntimeError("Could not fetch latest block number from Blockscout")


def _get_eth_price_usd() -> float:
    """Best-effort snapshot of ETH/USD price for metadata."""
    data = _get_json(f"{BLOCKSCOUT_BASE}/stats")
    try:
        price = data.get("coin_price") if data else None
        if price is not None:
            return float(price)
    except (TypeError, ValueError):
        pass
    return ETH_PRICE_FALLBACK_USD


def _fetch_transactions(block_number: int) -> List[Dict[str, Any]]:
    """Fetch all transactions for a block, paginated."""
    txs: List[Dict[str, Any]] = []
    page_url = f"{BLOCKSCOUT_BASE}/blocks/{block_number}/transactions"
    params: Dict[str, Any] = {}
    while True:
        data = _get_json(page_url, params=params)
        if not data:
            break
        for tx in data.get("items", []):
            from_addr = (tx.get("from") or {}).get("hash", "")
            to_addr   = (tx.get("to") or {}).get("hash", "") if tx.get("to") else ""
            txs.append({
                "hash":      tx.get("hash", ""),
                "from":      from_addr,
                "to":        to_addr,
                "value":     int(tx.get("value", 0) or 0),
                "gas":       int(tx.get("gas_limit", 21000) or 21000),
                "gasPrice":  int(tx.get("gas_price", 0) or 0),
                "nonce":     int(tx.get("nonce", 0) or 0),
                "timestamp": int(datetime.fromisoformat(
                    (tx.get("timestamp") or "1970-01-01T00:00:00").replace("Z", "+00:00")
                ).timestamp()) if isinstance(tx.get("timestamp"), str) else 0,
            })
        next_page_params = data.get("next_page_params")
        if not next_page_params:
            break
        params = next_page_params
        time.sleep(DEFAULT_RATE_DELAY_S)
    return txs


def _fetch_block(block_number: int) -> Optional[Dict[str, Any]]:
    """Fetch a single block + its transactions."""
    block = _get_json(f"{BLOCKSCOUT_BASE}/blocks/{block_number}")
    if not block:
        return None
    ts_iso = block.get("timestamp")
    if isinstance(ts_iso, str):
        ts_unix = int(datetime.fromisoformat(ts_iso.replace("Z", "+00:00")).timestamp())
    else:
        ts_unix = int(ts_iso or 0)
    txs = _fetch_transactions(block_number)
    return {
        "block_number":      int(block.get("height", block_number)),
        "timestamp":         ts_unix,
        "transaction_count": int(block.get("transaction_count", len(txs))),
        "block_size":        int(block.get("size", 0) or 0),
        "base_fee":          int(block.get("base_fee_per_gas", 0) or 0),
        "gas_used":          int(block.get("gas_used", 0) or 0),
        "gas_limit":         int(block.get("gas_limit", 30_000_000) or 30_000_000),
        "transactions":      txs,
    }


def extract(num_blocks: int = DEFAULT_NUM_BLOCKS,
            start_block: Optional[int] = None,
            out_path: str = DEFAULT_OUT_PATH) -> Dict[str, Any]:
    """Fetch num_blocks consecutive Ethereum blocks ending at start_block."""
    if start_block is None:
        start_block = _get_latest_block_number()
    print(f"Extracting {num_blocks} blocks ending at #{start_block} from Blockscout …")

    cache: Dict[str, Any] = {}
    failures = 0
    for i in range(num_blocks):
        n = start_block - i
        block = _fetch_block(n)
        if block is None:
            failures += 1
            print(f"  skip block {n} (fetch failed)", file=sys.stderr)
            time.sleep(DEFAULT_RATE_DELAY_S)
            continue
        cache[str(n)] = block
        if (i + 1) % 25 == 0:
            print(f"  fetched {i + 1}/{num_blocks} blocks (failures: {failures})")
        time.sleep(DEFAULT_RATE_DELAY_S)

    cache["_meta"] = {
        "block_range":    [start_block - num_blocks + 1, start_block],
        "retrieval_date": datetime.now(timezone.utc).isoformat(),
        "source_url":     BLOCKSCOUT_BASE,
        "eth_price_usd":  _get_eth_price_usd(),
        "num_blocks":     len(cache),
    }

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(cache, f, indent=2)
    print(f"\nWrote {len(cache) - 1} blocks + metadata to {out_path}")
    return cache


def main() -> None:
    num_blocks  = DEFAULT_NUM_BLOCKS
    start_block: Optional[int] = None

    if len(sys.argv) > 1:
        num_blocks = int(sys.argv[1])
    if len(sys.argv) > 2:
        start_block = int(sys.argv[2])

    extract(num_blocks=num_blocks, start_block=start_block)


if __name__ == "__main__":
    main()
