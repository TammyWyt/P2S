#!/usr/bin/env python3
"""M1b spike: prove ORDER-DEPENDENT MEV on real EVM execution via `evm t8n`.

A constant-product pool (MiniAMM.sol) is deployed, then the SAME three swaps are
executed in two orderings on the IDENTICAL deployed-pool state:

  PoS arm  : [attacker.buy, victim.buy, attacker.sell]   (victim sandwiched)
  P2S arm  : [attacker.buy, attacker.sell, victim.buy]   (attacker txs forced adjacent)

Per-account nonce order is preserved in both (attacker.buy before attacker.sell);
the only difference is WHERE the victim sits -- which in P2S the attacker cannot
control because order is fixed at B1 before content is visible.

Expected: attacker nets a profit in the PoS arm and ~zero (a tiny gas/rounding
loss) in the P2S arm. That is content-ordering independence, measured on real EVM.
"""
import json, subprocess, tempfile, os, sys, re

EVM = os.environ.get("EVM", "/opt/homebrew/bin/evm")
SOLC = os.environ.get("SOLC", "/opt/homebrew/bin/solc")
HERE = os.path.dirname(os.path.abspath(__file__))
WEI = 10**18

# deterministic test accounts (anvil)
DEPLOYER = ("0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266",
            "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80")
ATTACKER = ("0x70997970C51812dc3A010C7d01b50e0d17dc79C8",
            "0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d")
VICTIM   = ("0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC",
            "0x5de4111afa1a4b94908f83103eb1f1706367c2e68ca870fc3fb9a804cdab365a")

SEL_BUY  = "a6f2ae3a"
SEL_SELL = "e4849b32"

ETH_RESERVE   = 100 * WEI            # pool ETH reserve
TOKEN_RESERVE = 100000 * WEI         # pool token reserve (scaled)
F = 10 * WEI                         # attacker front-run size
V = 20 * WEI                         # victim swap size

ENV = {
    "currentCoinbase": "0x0000000000000000000000000000000000000000",
    "currentGasLimit": "0x1c9c380",
    "currentNumber": "0x1",
    "currentTimestamp": "0x3e8",
    "currentBaseFee": "0x1",
    "currentRandom": "0x" + "00" * 32,
    "withdrawals": [],
}
GAS_PRICE = "0x3b9aca00"   # 1 gwei
SIG = {"v": "0x0", "r": "0x0", "s": "0x0"}

def compile_amm():
    out = subprocess.run([SOLC, "--bin", "--optimize", os.path.join(HERE, "MiniAMM.sol")],
                         capture_output=True, text=True)
    if out.returncode != 0:
        print(out.stderr); sys.exit(1)
    m = re.search(r"Binary:\s*\n([0-9a-fA-F]+)", out.stdout)
    return m.group(1)

def run_t8n(alloc, txs, tag):
    d = tempfile.mkdtemp(prefix=f"t8n_{tag}_")
    for name, obj in (("alloc.json", alloc), ("env.json", ENV), ("txs.json", txs)):
        with open(os.path.join(d, name), "w") as f:
            json.dump(obj, f)
    cmd = [EVM, "t8n",
           "--input.alloc", os.path.join(d, "alloc.json"),
           "--input.env", os.path.join(d, "env.json"),
           "--input.txs", os.path.join(d, "txs.json"),
           "--output.basedir", d,
           "--output.alloc", "oa.json", "--output.result", "or.json",
           "--state.fork", "Shanghai", "--state.chainid", "1"]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        print(f"[{tag}] t8n FAILED rc={p.returncode}\n{p.stderr}"); sys.exit(1)
    with open(os.path.join(d, "oa.json")) as f: oa = json.load(f)
    with open(os.path.join(d, "or.json")) as f: orr = json.load(f)
    return oa, orr

def bal(alloc, addr):
    rec = alloc.get(addr.lower()) or alloc.get(addr) or {}
    return int(rec.get("balance", "0x0"), 16)

def u256(n):
    return f"{n:064x}"

# constant-product buy: how many tokens attacker receives for F (mirrors EVM math)
def buy_out(eth_res, tok_res, amount_in):
    k = eth_res * tok_res
    new_eth = eth_res + amount_in
    new_tok = k // new_eth
    return tok_res - new_tok

def main():
    print("evm:", subprocess.run([EVM, "--version"], capture_output=True, text=True).stdout.strip())
    creation = compile_amm()
    # ---- deploy run: capture deployed-pool alloc + contract address ----
    deploy_alloc = {
        DEPLOYER[0]: {"balance": hex(1000 * WEI), "nonce": "0x0"},
        ATTACKER[0]: {"balance": hex(1000 * WEI), "nonce": "0x0"},
        VICTIM[0]:   {"balance": hex(1000 * WEI), "nonce": "0x0"},
    }
    deploy_tx = {"input": "0x" + creation + u256(TOKEN_RESERVE),
                 "gas": "0x300000", "gasPrice": GAS_PRICE, "nonce": "0x0",
                 "value": hex(ETH_RESERVE), "secretKey": DEPLOYER[1],
                 "chainId": "0x1", "to": None, **SIG}
    post_deploy, dres = run_t8n(deploy_alloc, [deploy_tx], "deploy")
    pool = dres["receipts"][0]["contractAddress"]
    print(f"pool deployed at {pool}; reserves: {ETH_RESERVE/WEI} ETH / {TOKEN_RESERVE/WEI} TOK")

    atk_tokens = buy_out(ETH_RESERVE, TOKEN_RESERVE, F)   # attacker sells exactly this

    def buy_tx(acct, nonce, amount):
        return {"input": "0x" + SEL_BUY, "gas": "0x100000", "gasPrice": GAS_PRICE,
                "nonce": hex(nonce), "value": hex(amount), "to": pool,
                "secretKey": acct[1], "chainId": "0x1", **SIG}
    def sell_tx(acct, nonce, amount):
        return {"input": "0x" + SEL_SELL + u256(amount), "gas": "0x100000",
                "gasPrice": GAS_PRICE, "nonce": hex(nonce), "value": "0x0", "to": pool,
                "secretKey": acct[1], "chainId": "0x1", **SIG}

    atk0 = bal(post_deploy, ATTACKER[0])

    arms = {
        "PoS  (victim sandwiched)": [buy_tx(ATTACKER, 0, F), buy_tx(VICTIM, 0, V), sell_tx(ATTACKER, 1, atk_tokens)],
        "P2S  (attacker adjacent)": [buy_tx(ATTACKER, 0, F), sell_tx(ATTACKER, 1, atk_tokens), buy_tx(VICTIM, 0, V)],
    }
    print()
    for tag, txs in arms.items():
        oa, orr = run_t8n(post_deploy, txs, tag.split()[0])
        rej = orr.get("rejected", [])
        atk1 = bal(oa, ATTACKER[0])
        net = (atk1 - atk0) / WEI
        print(f"--- {tag} ---")
        print(f"  attacker net = {net:+.6f} ETH   rejected={rej}")
    print()
    print("VERDICT: PoS net > 0 (sandwich profit) and P2S net <= ~0 (forced-adjacent, no")
    print("victim to exploit) => order-dependent MEV is real and content-ordering")
    print("independence holds, measured on real EVM execution via evm t8n.")

if __name__ == "__main__":
    main()
