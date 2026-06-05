#!/usr/bin/env python3
"""
Benign-user revert-cost analysis — Ethereum mainnet vs. P2S (experiment E1).

Measures what a benign user whose transaction REVERTS (typically a DEX swap
that trips its slippage bound) pays today on Ethereum, and what the same user
would pay under P2S, where a reservation fee

    F_res = phi * gas_limit * base_fee          (phi ~ 0.20, burned in B1)

is charged on the *declared* gas limit regardless of execution outcome, on top
of the standard EIP-1559 execution fee on gas actually used in B2.

Cost models per reverted transaction:

    cost_eth_today = gas_used  * effective_gas_price
    cost_p2s       = F_res + cost_eth_today
    overhead       = cost_p2s / cost_eth_today

Data sources:
  * Blockscout v2 REST (same source as extract_ethereum_blocks.py) for
    receipt-level fields per tx (status, gas_used, gas_limit, gas_price,
    base_fee_per_gas, max_fee_per_gas, method, to) — one paginated call
    per block.
  * The public Blockscout instance does NOT decode revert reasons
    (transactions stay "awaiting_internal_transactions"), so reasons are
    recovered by replaying each reverted tx with eth_call at its parent
    block via a public JSON-RPC node and decoding the revert data
    (Error(string), Panic(uint256), or a custom-error selector resolved
    through the openchain.xyz signature database).
    Replay caveat: eth_call at the parent block misses in-block state.
    A replay that SUCCEEDS therefore means the failure was caused by
    in-block ordering (e.g. the pool price moved earlier in the same
    block) — for DEX swaps this is precisely the slippage case, and is
    reported as its own category `in_block_state_dependent`.

NOTE: data/ethereum_blocks_cache.json is NOT usable for this experiment —
its block numbers (~164.9M) do not exist on Ethereum mainnet (~25.2M as of
June 2026) and it carries no receipt fields. This script fetches fresh,
verifiable mainnet blocks instead.

Usage:
    python3 scripts/revert_cost_analysis.py fetch   [num_blocks] [start_block]
    python3 scripts/revert_cost_analysis.py analyze [--phi 0.20] [--reasons dex|all|none]

`fetch` writes data/revert_receipts_cache.json (checkpointed every 25 blocks,
resumable). `analyze` recovers and classifies revert reasons (slippage /
deadline / in-block state dependence / other), memoising RPC replays in
data/revert_reasons_cache.json, and writes data/revert_cost_analysis.json
plus a console summary. --reasons controls which reverted txs get the
RPC-replay treatment (default: dex — only DEX-router reverts).

Rate limit: 5 req/s (Blockscout public tier). 1000 blocks ~ 10 minutes.
"""

import http.client
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

BLOCKSCOUT_BASE = "https://eth.blockscout.com/api/v2"
OPENCHAIN_LOOKUP = "https://api.openchain.xyz/signature-database/v1/lookup"
RPC_URL = "https://ethereum-rpc.publicnode.com"
RECEIPTS_PATH = "data/revert_receipts_cache.json"
REASONS_PATH = "data/revert_reasons_cache.json"
ANALYSIS_PATH = "data/revert_cost_analysis.json"
DEFAULT_NUM_BLOCKS = 1000
DEFAULT_RATE_DELAY_S = 0.2     # 5 req/s
DEFAULT_PHI = 0.20             # recommended phi from the parametric analysis
CHECKPOINT_EVERY = 25

# Well-known mainnet DEX router / aggregator entry points (lowercase).
DEX_ROUTERS = {
    "0x7a250d5630b4cf539739df2c5dacb4c659f2488d": "Uniswap V2 Router02",
    "0xe592427a0aece92de3edee1f18e0157c05861564": "Uniswap V3 SwapRouter",
    "0x68b3465833fb72a70ecdf485e0e4c7bd8665fc45": "Uniswap V3 SwapRouter02",
    "0x3fc91a3afd70395cd496c647d5a6cc9d4b2b7fad": "Uniswap Universal Router",
    "0xef1c6e67703c7bd7107eed8303fbe6ec2554bf6b": "Uniswap Universal Router (old)",
    "0x66a9893cc07d91d95644aedd05d03f95e1dba8af": "Uniswap Universal Router v2",
    "0x1111111254eeb25477b68fb85ed929f73a960582": "1inch v5",
    "0x111111125421ca6dc452d289314280a0f8842a65": "1inch v6",
    "0xdef1c0ded9bec7f1a1670819833240f027b25eff": "0x Exchange Proxy",
    "0x881d40237659c251811cec9c364ef91dc08d300c": "MetaMask Swap Router",
    "0xd9e1ce17f2641f24ae83637ab66a2cca9c378b9f": "SushiSwap Router",
    "0x6131b5fae19ea4f9d964eac0408e4408b66337b5": "KyberSwap MetaAggregation v2",
    "0xdef171fe48cf0115b1d80b88dc8eab59176fee57": "ParaSwap v5",
}

# Revert-reason patterns (matched case-insensitively against the decoded
# reason or the openchain-resolved custom-error name).
SLIPPAGE_PATTERNS = [
    "insufficient_output_amount",   # Uniswap V2
    "excessive_input_amount",       # Uniswap V2 exact-out
    "too little received",          # Uniswap V3
    "too much requested",           # Uniswap V3 exact-out
    "toolittlereceived",            # UniversalRouter custom errors
    "toomuchrequested",
    "return amount is not enough",  # 1inch
    "returnamountisnotenough",
    "minreturn",
    "min return",
    "slippage",
    "insufficient output",
    "price impact",
]
DEADLINE_PATTERNS = [
    "expired",
    "transaction too old",
    "deadline",
]


# macOS framework Python ships without a CA bundle; fall back to the system
# one. Blockscout's CDN also rejects the default urllib user-agent.
_CAFILE = next((p for p in ("/etc/ssl/cert.pem",
                            "/opt/homebrew/etc/ca-certificates/cert.pem")
                if os.path.exists(p)), None)
_SSL_CTX = ssl.create_default_context(cafile=_CAFILE)
_HEADERS = {"accept": "application/json", "user-agent": "p2s-research/1.0"}


def _get_json(url: str, params: Optional[Dict[str, Any]] = None,
              timeout: int = 30, retries: int = 3) -> Optional[Dict[str, Any]]:
    """GET with simple backoff; returns parsed JSON or None on failure."""
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=_HEADERS)
            with urllib.request.urlopen(req, timeout=timeout,
                                        context=_SSL_CTX) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 429:                  # rate limit
                time.sleep(2 ** attempt)
                continue
            print(f"  HTTP {e.code}: {url}", file=sys.stderr)
            return None
        # OSError covers URLError, ConnectionResetError, RemoteDisconnected,
        # and socket timeouts; HTTPException covers other http.client errors.
        except (OSError, http.client.HTTPException, json.JSONDecodeError) as e:
            print(f"  request error: {e}", file=sys.stderr)
            time.sleep(2 ** attempt)
    return None


def _get_latest_block_number() -> int:
    data = _get_json(f"{BLOCKSCOUT_BASE}/blocks", params={"type": "block"})
    if data and data.get("items"):
        return int(data["items"][0]["height"])
    raise RuntimeError("Could not fetch latest block number from Blockscout")


def _get_eth_price_usd() -> Optional[float]:
    data = _get_json(f"{BLOCKSCOUT_BASE}/stats")
    try:
        return float(data["coin_price"]) if data and data.get("coin_price") else None
    except (TypeError, ValueError, KeyError):
        return None


def _int(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _fetch_block_receipts(block_number: int) -> Optional[Dict[str, Any]]:
    """Fetch a block's transactions with receipt-level fields, paginated."""
    block = _get_json(f"{BLOCKSCOUT_BASE}/blocks/{block_number}")
    if not block:
        return None
    txs: List[Dict[str, Any]] = []
    page_url = f"{BLOCKSCOUT_BASE}/blocks/{block_number}/transactions"
    params: Dict[str, Any] = {}
    while True:
        data = _get_json(page_url, params=params)
        if not data:
            break
        for tx in data.get("items", []):
            to = tx.get("to") or {}
            txs.append({
                "hash":           tx.get("hash", ""),
                "to":             (to.get("hash") or "").lower(),
                "to_name":        to.get("name") or "",
                "method":         tx.get("method") or "",
                "status":         tx.get("status") or "",       # "ok" | "error"
                "result":         tx.get("result") or "",
                "revert_reason":  tx.get("revert_reason"),
                "type":           tx.get("type"),
                "gas_limit":      _int(tx.get("gas_limit")),
                "gas_used":       _int(tx.get("gas_used")),
                "gas_price":      _int(tx.get("gas_price")),    # effective
                "max_fee_per_gas":          _int(tx.get("max_fee_per_gas")),
                "max_priority_fee_per_gas": _int(tx.get("max_priority_fee_per_gas")),
                "base_fee_per_gas":         _int(tx.get("base_fee_per_gas")),
            })
        next_page_params = data.get("next_page_params")
        if not next_page_params:
            break
        params = next_page_params
        time.sleep(DEFAULT_RATE_DELAY_S)
    return {
        "block_number": block_number,
        "timestamp":    block.get("timestamp", ""),
        "base_fee":     _int(block.get("base_fee_per_gas")),
        "gas_used":     _int(block.get("gas_used")),
        "gas_limit":    _int(block.get("gas_limit")),
        "transactions": txs,
    }


def fetch(num_blocks: int = DEFAULT_NUM_BLOCKS,
          start_block: Optional[int] = None,
          out_path: str = RECEIPTS_PATH) -> Dict[str, Any]:
    """Fetch receipt-level tx data for num_blocks ending at start_block.

    Resumable: blocks already present in out_path are skipped.
    """
    cache: Dict[str, Any] = {}
    if os.path.exists(out_path):
        with open(out_path) as f:
            cache = json.load(f)
        print(f"Resuming: {len([k for k in cache if k != '_meta'])} blocks already cached")

    if start_block is None:
        start_block = cache.get("_meta", {}).get("block_range", [None, None])[1] \
            or _get_latest_block_number()
    print(f"Fetching {num_blocks} blocks ending at #{start_block} from Blockscout ...")

    failures = 0
    fetched = 0
    for i in range(num_blocks):
        n = start_block - i
        if str(n) in cache:
            continue
        block = _fetch_block_receipts(n)
        if block is None:
            failures += 1
            print(f"  skip block {n} (fetch failed)", file=sys.stderr)
            time.sleep(DEFAULT_RATE_DELAY_S)
            continue
        cache[str(n)] = block
        fetched += 1
        if fetched % CHECKPOINT_EVERY == 0:
            _save(cache, out_path, start_block, num_blocks)
            print(f"  fetched {fetched} new blocks "
                  f"({i + 1}/{num_blocks} scanned, failures: {failures})")
        time.sleep(DEFAULT_RATE_DELAY_S)

    _save(cache, out_path, start_block, num_blocks)
    n_blocks = len([k for k in cache if k != "_meta"])
    n_txs = sum(len(b["transactions"]) for k, b in cache.items() if k != "_meta")
    print(f"\nWrote {n_blocks} blocks / {n_txs} transactions to {out_path}")
    return cache


def _dump_json(obj: Any, path: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f)
    os.replace(tmp, path)


def _save(cache: Dict[str, Any], out_path: str,
          start_block: int, num_blocks: int) -> None:
    cache["_meta"] = {
        "block_range":    [start_block - num_blocks + 1, start_block],
        "retrieval_date": datetime.now(timezone.utc).isoformat(),
        "source_url":     BLOCKSCOUT_BASE,
        "eth_price_usd":  cache.get("_meta", {}).get("eth_price_usd") or _get_eth_price_usd(),
        "num_blocks":     len([k for k in cache if k != "_meta"]),
    }
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    tmp = out_path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(cache, f)
    os.replace(tmp, out_path)


# --------------------------------------------------------------------------
# Revert-reason recovery (eth_call replay at parent block)
# --------------------------------------------------------------------------

_selector_memo: Dict[str, Optional[str]] = {}


def _resolve_selector(selector: str) -> Optional[str]:
    """Resolve a 4-byte custom-error/function selector via openchain.xyz."""
    if selector in _selector_memo:
        return _selector_memo[selector]
    data = _get_json(OPENCHAIN_LOOKUP, params={"function": selector, "filter": "true"})
    name = None
    try:
        entries = data["result"]["function"].get(selector) or []
        if entries:
            name = entries[0]["name"]
    except (TypeError, KeyError):
        pass
    _selector_memo[selector] = name
    return name


def _rpc(method: str, params: List[Any],
         timeout: int = 30, retries: int = 3) -> Dict[str, Any]:
    """JSON-RPC POST; returns the full response object ({result} or {error})."""
    body = json.dumps({"jsonrpc": "2.0", "id": 1,
                       "method": method, "params": params}).encode()
    for attempt in range(retries):
        try:
            req = urllib.request.Request(RPC_URL, data=body, headers={
                "content-type": "application/json", **_HEADERS})
            with urllib.request.urlopen(req, timeout=timeout,
                                        context=_SSL_CTX) as resp:
                return json.loads(resp.read().decode())
        except (OSError, http.client.HTTPException, json.JSONDecodeError) as e:
            print(f"  rpc error: {e}", file=sys.stderr)
            time.sleep(2 ** attempt)
    return {}


def _decode_revert_data(data: str) -> Dict[str, Any]:
    """Decode eth_call revert data into a human-readable reason."""
    if not data or data == "0x":
        return {"reason": None, "kind": "no_reason_data"}
    if data.startswith("0x08c379a0"):          # Error(string)
        try:
            raw = bytes.fromhex(data[10:])
            strlen = int.from_bytes(raw[32:64], "big")
            return {"reason": raw[64:64 + strlen].decode(errors="replace"),
                    "kind": "error_string"}
        except (ValueError, IndexError):
            return {"reason": data[:138], "kind": "undecodable"}
    if data.startswith("0x4e487b71"):          # Panic(uint256)
        code = int(data[10:74] or "0", 16) if len(data) >= 74 else None
        return {"reason": f"Panic({code})", "kind": "panic"}
    selector = data[:10]
    resolved = _resolve_selector(selector)
    return {"reason": resolved or selector,
            "kind": "custom_error" if resolved else "unresolved_selector"}


def _replay_revert_reason(tx_hash: str) -> Dict[str, Any]:
    """Re-execute a reverted tx via eth_call at its parent block.

    Returns {reason, kind} where kind is one of: error_string, custom_error,
    panic, no_reason_data, unresolved_selector, in_block_state_dependent
    (replay succeeded at parent state), undecodable, rpc_failed.
    """
    tx = _rpc("eth_getTransactionByHash", [tx_hash]).get("result")
    if not tx:
        return {"reason": None, "kind": "rpc_failed"}
    call = {"from": tx["from"], "to": tx["to"],
            "data": tx["input"], "value": tx["value"], "gas": tx["gas"]}
    parent = hex(int(tx["blockNumber"], 16) - 1)
    resp = _rpc("eth_call", [call, parent])
    if not resp:
        return {"reason": None, "kind": "rpc_failed"}
    if "error" not in resp:
        # Succeeds against parent state => failure was caused by in-block
        # ordering (e.g. pool price moved earlier in the same block).
        return {"reason": None, "kind": "in_block_state_dependent"}
    return _decode_revert_data(resp["error"].get("data") or "")


def _categorize(reason_info: Dict[str, Any], is_dex: bool) -> str:
    """Map a recovered reason to slippage / deadline / other / ... category."""
    kind = reason_info.get("kind")
    if kind == "in_block_state_dependent":
        # For DEX swaps, in-block price movement tripping the bound IS the
        # slippage case; keep it distinct so the paper can report both
        # readings (conservative: exclude; inclusive: count as slippage).
        return "in_block_state_dependent"
    if kind in ("rpc_failed", "undecodable"):
        return "unknown"
    if kind == "no_reason_data":
        return "no_reason_data"
    text = (reason_info.get("reason") or "").lower()
    if any(p in text for p in SLIPPAGE_PATTERNS):
        return "slippage"
    if any(p in text for p in DEADLINE_PATTERNS):
        return "deadline"
    return "other"


# --------------------------------------------------------------------------
# Analysis
# --------------------------------------------------------------------------


def _is_dex(tx: Dict[str, Any]) -> bool:
    if tx["to"] in DEX_ROUTERS:
        return True
    name = (tx.get("to_name") or "").lower()
    return any(s in name for s in ("router", "aggregat", "swap"))


def _percentiles(values: List[float]) -> Dict[str, float]:
    if not values:
        return {}
    s = sorted(values)
    pick = lambda q: s[min(len(s) - 1, int(q * len(s)))]
    return {
        "n":      len(s),
        "mean":   sum(s) / len(s),
        "p10":    pick(0.10),
        "median": pick(0.50),
        "p90":    pick(0.90),
        "p99":    pick(0.99),
    }


def analyze(phi: float = DEFAULT_PHI,
            reasons_scope: str = "dex",
            receipts_path: str = RECEIPTS_PATH,
            reasons_path: str = REASONS_PATH,
            out_path: str = ANALYSIS_PATH) -> Dict[str, Any]:
    with open(receipts_path) as f:
        cache = json.load(f)
    meta = cache.get("_meta", {})
    eth_usd = meta.get("eth_price_usd")

    # On-disk memo of RPC replays so re-runs don't refetch.
    reasons_memo: Dict[str, Dict[str, Any]] = {}
    if os.path.exists(reasons_path):
        with open(reasons_path) as f:
            reasons_memo = json.load(f)

    total = reverted = dex_total = dex_reverted = 0
    revert_rows: List[Dict[str, Any]] = []
    success_dex_headroom: List[float] = []
    replayed = 0

    for key, block in cache.items():
        if key == "_meta":
            continue
        base_fee = block["base_fee"]
        for tx in block["transactions"]:
            if not tx["gas_used"] and tx["status"] not in ("ok", "error"):
                continue                       # pending/dropped artifacts
            total += 1
            is_dex = _is_dex(tx)
            if is_dex:
                dex_total += 1
                if tx["status"] == "ok" and tx["gas_used"] > 0:
                    success_dex_headroom.append(tx["gas_limit"] / tx["gas_used"])
            if tx["status"] != "error":
                continue
            reverted += 1
            if is_dex:
                dex_reverted += 1
            want_reason = (reasons_scope == "all"
                           or (reasons_scope == "dex" and is_dex))
            if want_reason:
                info = reasons_memo.get(tx["hash"])
                if info is None or info.get("kind") == "rpc_failed":
                    info = _replay_revert_reason(tx["hash"])
                    reasons_memo[tx["hash"]] = info
                    replayed += 1
                    if replayed % 25 == 0:
                        _dump_json(reasons_memo, reasons_path)
                        print(f"  replayed {replayed} reverted txs ...")
                    time.sleep(DEFAULT_RATE_DELAY_S)
                category = _categorize(info, is_dex)
            else:
                info = {"reason": None, "kind": "not_replayed"}
                category = "not_replayed"
            eff_price = tx["gas_price"] or (base_fee + tx["max_priority_fee_per_gas"])
            cost_today = tx["gas_used"] * eff_price                     # wei
            f_res = phi * tx["gas_limit"] * (tx["base_fee_per_gas"] or base_fee)
            revert_rows.append({
                "hash":        tx["hash"],
                "block":       block["block_number"],
                "to":          tx["to"],
                "router":      DEX_ROUTERS.get(tx["to"], tx["to_name"] or None),
                "is_dex":      is_dex,
                "method":      tx["method"],
                "category":    category,
                "reason":      info.get("reason"),
                "reason_kind": info.get("kind"),
                "gas_limit":   tx["gas_limit"],
                "gas_used":    tx["gas_used"],
                "utilization": tx["gas_used"] / tx["gas_limit"] if tx["gas_limit"] else None,
                "cost_today_eth": cost_today / 1e18,
                "f_res_eth":      f_res / 1e18,
                "cost_p2s_eth":   (f_res + cost_today) / 1e18,
                "overhead_ratio": (f_res + cost_today) / cost_today if cost_today else None,
            })
    _dump_json(reasons_memo, reasons_path)

    def stats(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
        return {
            "utilization":    _percentiles([r["utilization"] for r in rows if r["utilization"]]),
            "cost_today_eth": _percentiles([r["cost_today_eth"] for r in rows]),
            "f_res_eth":      _percentiles([r["f_res_eth"] for r in rows]),
            "overhead_ratio": _percentiles([r["overhead_ratio"] for r in rows if r["overhead_ratio"]]),
        }

    slippage_rows = [r for r in revert_rows if r["category"] == "slippage"]
    # Inclusive reading: explicit slippage reasons + DEX reverts that only
    # fail with in-block state (price moved within the block).
    slippage_incl_rows = [r for r in revert_rows
                          if r["category"] == "slippage"
                          or (r["category"] == "in_block_state_dependent"
                              and r["is_dex"])]
    dex_rows = [r for r in revert_rows if r["is_dex"]]
    by_category: Dict[str, int] = {}
    for r in revert_rows:
        by_category[r["category"]] = by_category.get(r["category"], 0) + 1

    result = {
        "_meta": {
            "phi":            phi,
            "reasons_scope":  reasons_scope,
            "blocks":         meta.get("num_blocks"),
            "block_range":    meta.get("block_range"),
            "eth_price_usd":  eth_usd,
            "analysis_date":  datetime.now(timezone.utc).isoformat(),
        },
        "counts": {
            "total_txs":        total,
            "reverted":         reverted,
            "revert_rate":      reverted / total if total else None,
            "dex_txs":          dex_total,
            "dex_reverted":     dex_reverted,
            "dex_revert_rate":  dex_reverted / dex_total if dex_total else None,
            "reverts_by_category": by_category,
        },
        "stats_all_reverts":      stats(revert_rows),
        "stats_dex_reverts":      stats(dex_rows),
        "stats_slippage_reverts": stats(slippage_rows),
        "stats_slippage_inclusive": stats(slippage_incl_rows),
        "successful_dex_headroom": _percentiles(success_dex_headroom),
        "reverted_txs": revert_rows,
    }

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(result, f, indent=2)

    # Console summary
    c = result["counts"]
    print(f"\n=== Revert cost analysis (phi = {phi}) ===")
    print(f"Blocks: {result['_meta']['blocks']}   Txs: {c['total_txs']}")
    print(f"Reverted: {c['reverted']} ({100 * c['revert_rate']:.2f}%)   "
          f"DEX reverted: {c['dex_reverted']}/{c['dex_txs']} "
          f"({100 * (c['dex_revert_rate'] or 0):.2f}%)")
    print(f"Revert categories: {c['reverts_by_category']}")
    for label, key in [("ALL reverts", "stats_all_reverts"),
                       ("DEX reverts", "stats_dex_reverts"),
                       ("SLIPPAGE reverts (explicit)", "stats_slippage_reverts"),
                       ("SLIPPAGE reverts (incl. in-block)", "stats_slippage_inclusive")]:
        st = result[key]
        if not st["overhead_ratio"]:
            print(f"\n{label}: no samples")
            continue
        ov, ut, ct, fr = (st["overhead_ratio"], st["utilization"],
                          st["cost_today_eth"], st["f_res_eth"])
        usd = f" (${ct['median'] * eth_usd:.2f} / ${fr['median'] * eth_usd:.2f} median)" \
            if eth_usd else ""
        print(f"\n{label} (n={ov['n']}):")
        print(f"  gas utilization at revert: median {ut['median']:.2f}, p90 {ut['p90']:.2f}")
        print(f"  cost today vs F_res (ETH, median): "
              f"{ct['median']:.6f} vs {fr['median']:.6f}{usd}")
        print(f"  P2S/today overhead ratio: median {ov['median']:.2f}x, "
              f"p90 {ov['p90']:.2f}x, p99 {ov['p99']:.2f}x")
    hd = result["successful_dex_headroom"]
    if hd:
        print(f"\nSuccessful DEX swaps gas headroom (limit/used): "
              f"median {hd['median']:.2f}x, p90 {hd['p90']:.2f}x (n={hd['n']})")
    print(f"\nWrote {out_path}")
    return result


def main() -> None:
    args = sys.argv[1:]
    if not args or args[0] not in ("fetch", "analyze"):
        print(__doc__)
        sys.exit(1)
    if args[0] == "fetch":
        num_blocks = int(args[1]) if len(args) > 1 else DEFAULT_NUM_BLOCKS
        start_block = int(args[2]) if len(args) > 2 else None
        fetch(num_blocks=num_blocks, start_block=start_block)
    else:
        phi = DEFAULT_PHI
        reasons_scope = "dex"
        if "--phi" in args:
            phi = float(args[args.index("--phi") + 1])
        if "--reasons" in args:
            reasons_scope = args[args.index("--reasons") + 1]
            if reasons_scope not in ("dex", "all", "none"):
                print("--reasons must be dex, all, or none", file=sys.stderr)
                sys.exit(1)
        analyze(phi=phi, reasons_scope=reasons_scope)


if __name__ == "__main__":
    main()
