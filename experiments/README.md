# Experiments

Follow-up experiments for the P2S paper. Each topic folder holds everything for its
experiments: the scripts, `data/` (results, committed), `cache/` (raw inputs and logs,
not committed) and `figures/`. Run every script from the repo root, e.g.
`python3 experiments/metadata/selective_reveal.py`.

The paper's own simulator and figures stay in `scripts/`, `data/` and `figures/`.

## Rules for a new experiment

1. Put it in the topic folder it belongs to, or create a new topic folder.
2. Name the script after what it measures. No numbers.
3. Write only inside that folder: results to `data/<script>.json`, raw downloads to
   `cache/<script>_…/`, logs to `cache/logs/`.
4. Add a row to the table below before running it. If the name is already taken,
   pick another.

## Registry

| Folder | Script | Question | Output (`data/`) | Was |
|---|---|---|---|---|
| metadata | `router_fingerprint.py` | Can public PHT fields tell DEX-router traffic apart? | prints only | E0 |
| metadata | `fetch_swap_logs.py`, `fetch_token1.py` | Swap/Sync logs and pool tokens, 1,004-block window | `token1.json`, cache | E1 fetch, E1b |
| metadata | `pool_fingerprint.py` | What a metadata-only attacker earns, ranking PHTs by P(swap) | `pool_fingerprint.json` | E1 |
| metadata | `fetch_swap_labels.py`, `swap_labels.py` | Sender, gas, fee fields and (pool, direction) labels | cache | E7 fetch |
| metadata | `fetch_victim_history.py` | The 45 victims and each sender's earlier history | `victims.json`, cache | E7b |
| metadata | `predict_pool_direction.py` | Top-1 pool+direction prediction from public fields: p = 24% | `predict_pool_direction.json` | E7 |
| metadata | `bet_before_cards.py` | Blind-bet bound on the 45 replayed sandwiches | `bet_before_cards.json` | E6 |
| metadata | `selective_reveal.py` | Which sandwiches stay worth attempting at phi = 0.2 | `selective_reveal.json` | E8 |
| reveal_agreement | `adversarial_reveal.py` | Straddling and selective reveals vs local E and f+1 rule | `adversarial_reveal.json` | E3 |
| reveal_agreement | `threshold_measured.py` | Measured disagreement under the f+1 rule | `threshold_measured.json` | E3b |
| reveal_agreement | `divergence.py` | Reveal-set divergence: straddle, partial, partition, Byzantine timing | `divergence.json` | E9 |
| reveal_agreement | `setunion_latency.py` | Extra latency of the set-union round at N = 1,000 | `setunion_latency.json` | E10 |
| reorg | `head_votes.py` | Real mainnet head-vote share per slot | `head_votes.json` | E4a |
| reorg | `reorg_replay.py` | The 45 sandwiches replayed in the reorg scenario | `reorg_replay.json` | E4c |
| comparison | `head_to_head.py` | P2S vs PoS and EIP-8209 on one workload | `head_to_head.json` | E5 |
| comparison | `three_way.py` | P2S vs Shutter vs BEAT-MEV slot time and bandwidth | `three_way.json` | E11 |
| utilization | `rational_declaration.py` | Utilization under learned gas limits; u* sweep (Table 4) | `rational_declaration.json` | E2 |
| utilization | `honest_phi.py` | What honest users pay under the fee rule | `honest_phi.json` | E2b |
| utilization | `gas_margin.py` | Declaring margin x eth_estimateGas: utilization and new failures | `gas_margin.json` | E12 |
| utilization | `target_090.py` | Declaring tightly enough for u* = 0.9: how many run out of gas | `target_090.json` | E15 |
| utilization | `ustar_rerun.py [u*]` | Every u*-dependent result at another target (default 0.6) | `ustar_<u*>/`, `figures/ustar_<u*>/` | E14 |

Shared code: `common/netgraph.py` (the network model as one weighted graph; was `e_net.py`).

## Not yet moved

`scripts/experiments/e13_*.py` and `data/experiments/` (PHT classification and the
end-to-end attack simulation) belong to a run that was still in progress when this folder
was set up. They move here once that run finishes.

## Inputs that need restoring or network access

- `metadata/cache/inputs_swap_logs.tgz` and `inputs_swap_labels.tgz` hold the raw on-chain
  inputs. They stay local and are not committed. Unpack with
  `tar xzf experiments/metadata/cache/inputs_swap_logs.tgz -C experiments/metadata/cache`
  (and the same for `inputs_swap_labels.tgz`), or refetch with the `fetch_*.py` scripts.
- `gas_margin.py` and `target_090.py` need an archive RPC with historical
  `eth_estimateGas` and `eth_simulateV1`: `source real/.env.local` first.
- `head_votes.py` reads the beacon chain.
