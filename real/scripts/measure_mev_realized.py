#!/usr/bin/env python3
"""Realized sandwich-MEV of P2S vs PoS, replayed on a real EVM.

Unlike measure_mev.py (which sizes a PROFIT-MAXIMIZING front-run and thus reports
an extractable upper bound ~34x realized), this replays each detected sandwich
with the attacker's ACTUAL on-chain front-run size, so the measured PoS MEV
matches the independently detected on-chain profit (a two-way validation of the
faithful replay). It then re-executes the same trade under the P2S ordering
(attacker's two legs forced adjacent, blind), where a rational attacker only
acts on positive profit, so P2S extractable MEV floors at 0.

Inputs : real/data/sandwiches.json  (attacked_trades_v2 from detect_sandwiches.py)
Output : real/data/mev_measured_realized.json
Needs  : evm (go-ethereum t8n) and solc on PATH; see measure_mev.py for env vars.
"""
import json, os, importlib.util

HERE = os.path.dirname(os.path.abspath(__file__))
WEI = 10**18

# reuse the faithful-EVM machinery (t8n, MiniAMM compile, V2 math) from measure_mev
_spec = importlib.util.spec_from_file_location("mm", os.path.join(HERE, "measure_mev.py"))
mm = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(mm)


def run():
    s = json.load(open(os.path.join(HERE, "..", "data", "sandwiches.json")))
    trades = [a for a in s["attacked_trades_v2"]
              if a["reserve_eth_wei"] > 0 and a["victim_weth_in_eth"] > 0
              and a["front_weth_in_eth"] > 0]
    creation = mm.compile_amm()
    pos_tot = p2s_tot = onchain_tot = 0.0
    rows = []
    for a in trades:
        Re, Rt = int(a["reserve_eth_wei"]), int(a["reserve_token"])
        V = int(round(a["victim_weth_in_eth"] * WEI))
        F = int(round(a["front_weth_in_eth"] * WEI))          # REAL front-run, not optimal
        dalloc = {x[0]: {"balance": mm.FUND, "nonce": "0x0"}
                  for x in (mm.DEPLOYER, mm.ATTACKER, mm.VICTIM)}
        dtx = {"input": "0x" + creation + mm.u256(Rt), "gas": "0x400000",
               "gasPrice": mm.GAS_PRICE, "nonce": "0x0", "value": hex(Re),
               "secretKey": mm.DEPLOYER[1], "chainId": "0x1", "to": None, **mm.SIG}
        post, dres = mm.t8n(dalloc, [dtx])
        pool = dres["receipts"][0]["contractAddress"]
        atk_tokens = mm.amt_out(F, Re, Rt)

        def buy(acct, n, amt):
            return {"input": "0x" + mm.SEL_BUY, "gas": "0x200000", "gasPrice": mm.GAS_PRICE,
                    "nonce": hex(n), "value": hex(amt), "to": pool, "secretKey": acct[1],
                    "chainId": "0x1", **mm.SIG}

        def sell(acct, n, amt):
            return {"input": "0x" + mm.SEL_SELL + mm.u256(amt), "gas": "0x200000",
                    "gasPrice": mm.GAS_PRICE, "nonce": hex(n), "value": "0x0", "to": pool,
                    "secretKey": acct[1], "chainId": "0x1", **mm.SIG}

        atk0 = mm.bal(post, mm.ATTACKER[0])
        pos, _ = mm.t8n(post, [buy(mm.ATTACKER, 0, F), buy(mm.VICTIM, 0, V), sell(mm.ATTACKER, 1, atk_tokens)])
        p2s, _ = mm.t8n(post, [buy(mm.ATTACKER, 0, F), sell(mm.ATTACKER, 1, atk_tokens), buy(mm.VICTIM, 0, V)])
        pos_mev = (mm.bal(pos, mm.ATTACKER[0]) - atk0) / WEI
        p2s_mev = (mm.bal(p2s, mm.ATTACKER[0]) - atk0) / WEI
        pos_tot += max(0.0, pos_mev)
        p2s_tot += max(0.0, p2s_mev)
        onchain_tot += a["profit_eth"]
        rows.append({"block": a["block"], "pool": a["pool"], "victim_weth": V / WEI,
                     "front_run_eth": F / WEI, "onchain_profit_eth": a["profit_eth"],
                     "pos_mev_eth": pos_mev, "p2s_mev_eth": p2s_mev})
        print(f"blk {a['block']} V={V/WEI:.3f} F={F/WEI:.3f}  "
              f"onchain={a['profit_eth']:+.5f}  PoS={pos_mev:+.5f}  P2S={p2s_mev:+.5f} ETH", flush=True)

    red = 100.0 * (1 - p2s_tot / pos_tot) if pos_tot > 0 else float("nan")
    summary = {"mode": "realized", "n": len(rows),
               "pos_total_mev_eth": pos_tot, "p2s_total_mev_eth": p2s_tot,
               "onchain_detected_total_eth": onchain_tot,
               "replay_vs_detection_ratio": (pos_tot / onchain_tot) if onchain_tot else None,
               "reduction_pct": red, "per_fixture": rows}
    out = os.path.join(HERE, "..", "data", "mev_measured_realized.json")
    json.dump(summary, open(out, "w"), indent=2)
    print(f"\n==== REALIZED over {len(rows)} real sandwiches ====")
    print(f"PoS MEV (t8n)        : {pos_tot:.4f} ETH")
    print(f"on-chain detected    : {onchain_tot:.4f} ETH  (validation)")
    print(f"P2S MEV (t8n)        : {p2s_tot:.4f} ETH")
    print(f"Reduction            : {red:.2f}%")
    print(f"wrote {out}")


if __name__ == "__main__":
    run()
