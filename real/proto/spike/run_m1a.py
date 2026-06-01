#!/usr/bin/env python3
"""M1a spike: prove `evm t8n` executes an EXPLICITLY ORDERED tx list and threads
state between txs, so that reordering the same txs changes the post-state.

Scenario (pure ETH transfers, no contracts):
  A starts with 2 ETH (nonce 0). B and C start empty.
  txA: A -> B, 1.5 ETH (from A, nonce 0)
  txB: B -> C, 1.0 ETH (from B, nonce 0)   <- only fundable AFTER txA executes

  order [txA, txB]: both succeed; C ends with 1.0 ETH.
  order [txB, txA]: txB has no funds when it runs first -> rejected;
                    C ends with 0 ETH.

Different orderings of the SAME txs => different post-state. That is exactly the
property P2S's forced B1 ordering relies on.
"""
import json, subprocess, tempfile, os, sys

EVM = os.environ.get("EVM", "/opt/homebrew/bin/evm")

# anvil/hardhat well-known test accounts (deterministic)
A_ADDR = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"
A_KEY  = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
B_ADDR = "0x70997970C51812dc3A010C7d01b50e0d17dc79C8"
B_KEY  = "0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d"
C_ADDR = "0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC"

WEI = 10**18
def hexwei(eth_float):
    return hex(int(eth_float * WEI))

ALLOC = {
    A_ADDR: {"balance": hexwei(2.0), "nonce": "0x0"},
    B_ADDR: {"balance": "0x0", "nonce": "0x0"},
    C_ADDR: {"balance": "0x0", "nonce": "0x0"},
}

ENV = {
    "currentCoinbase": "0x0000000000000000000000000000000000000000",
    "currentGasLimit": "0x1c9c380",          # 30M
    "currentNumber": "0x1",
    "currentTimestamp": "0x3e8",
    "currentBaseFee": "0x1",                  # ~0, so gasPrice 1gwei is valid
    "currentRandom": "0x0000000000000000000000000000000000000000000000000000000000000000",
    "withdrawals": [],
}

GAS_PRICE = "0x3b9aca00"  # 1 gwei

# v/r/s zero placeholders are required by t8n's tx unmarshaller; it re-signs from secretKey.
_SIG = {"v": "0x0", "r": "0x0", "s": "0x0"}
txA = {"input": "0x", "gas": "0x5208", "gasPrice": GAS_PRICE, "nonce": "0x0",
       "to": B_ADDR, "value": hexwei(1.5), "secretKey": A_KEY, "chainId": "0x1", **_SIG}
txB = {"input": "0x", "gas": "0x5208", "gasPrice": GAS_PRICE, "nonce": "0x0",
       "to": C_ADDR, "value": hexwei(1.0), "secretKey": B_KEY, "chainId": "0x1", **_SIG}

def run_t8n(txs, tag):
    d = tempfile.mkdtemp(prefix=f"t8n_{tag}_")
    for name, obj in (("alloc.json", ALLOC), ("env.json", ENV), ("txs.json", txs)):
        with open(os.path.join(d, name), "w") as f:
            json.dump(obj, f)
    cmd = [EVM, "t8n",
           "--input.alloc", os.path.join(d, "alloc.json"),
           "--input.env", os.path.join(d, "env.json"),
           "--input.txs", os.path.join(d, "txs.json"),
           "--output.basedir", d,
           "--output.alloc", "out_alloc.json",
           "--output.result", "out_result.json",
           "--state.fork", "Shanghai",
           "--state.chainid", "1"]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        print(f"[{tag}] evm t8n FAILED rc={p.returncode}")
        print(p.stderr)
        sys.exit(1)
    with open(os.path.join(d, "out_alloc.json")) as f:
        out_alloc = json.load(f)
    with open(os.path.join(d, "out_result.json")) as f:
        out_result = json.load(f)
    return out_alloc, out_result

def bal(alloc, addr):
    rec = alloc.get(addr.lower()) or alloc.get(addr) or {}
    return int(rec.get("balance", "0x0"), 16) / WEI

print("evm:", subprocess.run([EVM, "--version"], capture_output=True, text=True).stdout.strip())
print()

for tag, txs in (("ORDERED [A->B, B->C]", [txA, txB]),
                 ("REORDERED [B->C, A->B]", [txB, txA])):
    out_alloc, out_result = run_t8n(txs, tag.split()[0])
    rejected = out_result.get("rejected", [])
    print(f"--- {tag} ---")
    print(f"  C balance = {bal(out_alloc, C_ADDR):.4f} ETH   rejected={rejected}")

print()
print("VERDICT: if C differs between the two runs, t8n respects explicit ordering")
print("and threads state across txs -> the forced-ordering primitive works.")
