# P2S (Proposer in 2 Steps) Consensus Protocol

A novel consensus mechanism designed to mitigate MEV (Maximal Extractable Value) attacks through a two-step block proposal process with hidden transaction details.

## Overview

P2S implements a **two-step block proposal mechanism** where:
1. **B1 Block**: Contains PHTs (Partially Hidden Transactions) with concealed sensitive fields
2. **B2 Block**: Contains MTs (Matching Transactions) with revealed details after B1 confirmation

This design prevents MEV attacks by hiding transaction details until after block commitment, while maintaining compatibility with Ethereum's consensus mechanism.

## Simulation Parameters and Calibration

The tables below list all simulation constants used in the paper's evaluation, with their empirical sources. Each input distribution is tagged as empirically **calibrated** or **assumed**.

### Agent-based simulation parameters (φ sweep)

| Parameter | Value | Description | Source |
|---|---|---|---|
| **MEV gain distributions** | | | |
| `MEV_MU` | ln(0.00056) | LogNormal median, standard MEV (≈ measured median) | Calibrated ‡ |
| `MEV_SIG` | 2.85 | LogNormal spread (tail) | Literature ‡ |
| `MEV_CAP` | 50.0 ETH | Single-event cap | Literature |
| `BLIND_MU` | ln(0.0003) | LogNormal median, blind PHT gain | Calibrated ‡ |
| `BLIND_SIG` | 2.5 | LogNormal spread, blind PHT gain | Literature |
| **BlindPlanterBot** | | | |
| `BLIND_FIT` | 0.10 | Blind PHT alignment rate per block | Calibrated † |
| `BLIND_SUCCESS` | 0.50 | Success given alignment | Calibrated † |
| **CrossBlockArbBot** | | | |
| `ARB_OPP_P2S` | 0.10 | Cross-DEX arb opportunity rate | Qin et al. (2021) |
| `ARB_EXEC` | 0.60 | Arb execution success rate | Qin et al. (2021) |
| `ARB_EFF` | 0.80 | Price-efficiency capture | Calibrated |
| **BlockStufferBot** | | | |
| `STUFF_N_PHTS` | 10 | Dummy PHTs per stuffing attempt | Calibrated |
| `STUFF_GAS` | 1.2M gas | Declared gas per dummy PHT | Calibrated |
| **Gas and network** | | | |
| `ḡ` | 45.1 gwei | Median base fee (1,005 mainnet blocks) | Blockscout |
| Priority fee | 1.5 gwei | Median priority fee (post-Merge) | Blockscout |
| `N_p` | 5 | Proposers in test committee | Design |
| **Sweep configuration** | | | |
| \|Φ\| | 21 | φ values, log-spaced 10⁻⁴–1 | |
| Reps | 3 | Seeds per (φ, rep) point | |
| Blocks/pt | 3,000 | Blocks per grid point | |

† `BLIND_FIT` and `BLIND_SUCCESS` represent the information asymmetry of a blind attacker; not directly observable from public data. The paper's sensitivity analysis (11 × 11 grid sweep) bounds the residual uncertainty.

‡ The **median** (0.00056 ETH) is anchored to our own on-chain sandwich detection (55 real Uniswap V2/V3 attacks over 400 sampled mainnet blocks; see `real/data/sandwiches.json`). The **spread σ and the tail** are set from the published MEV literature (Qin et al. 2021; Chi et al. 2024, arXiv:2405.17944; Torres et al. 2024), not from that small low-fee sample, which under-counts whales; the resulting mean is ≈0.033 ETH (≈$99 at ETH=$3,000), with rare whale sandwiches reaching tens of ETH.

### Block-level simulation parameters (P2S vs. Ethereum PoS comparison)

| Parameter | Value | Description |
|---|---|---|
| Blocks simulated | 1,000 | Drawn from 1,005-block mainnet cache |
| Slot time | 12 s | Both P2S and PoS baseline |
| B1 / B2 phase | 6 s each | P2S two-step split |
| Gas limit | 30M gas | Post-EIP-1559 mainnet |
| Proposers | 5 | Round-robin slot selection |
| Base fee fraction | 80% | EIP-1559 approximation |
| Block issuance | 0 ETH | Post-Merge: execution layer has no block subsidy |
| Attester reward | 0.06 ETH/slot | Consensus-layer reward (EIP-3675 approx.) |
| Proposer tip | 10% of fees | EIP-1559 priority-fee tip to proposer |
| Sandwich success | 35% | Probability given visibility |
| Front-run success | 50% | Calibrated ‡ |
| Arb block freq. | 15% | Fraction of blocks with arb opportunity |

## Reproducibility

The two evaluation axes use distinct artifacts:

- **Network-environment figures** (latency, bandwidth, block-size, and fan-out sweeps): discrete-event simulator (`scripts/simulation/netsim.py`) run over 100 seeds from a fixed master seed; deterministic.
- **Agent-based MEV and φ-sweep figures**: agent simulator (`scripts/simulation/agents.py`) and sweep driver (`plots/plot_phi_sweep.py`).
- **Block-level welfare / MEV-totals figures**: block simulator (`scripts/simulation/simulator.py`), seeded (`random.seed(42)`); deterministic.

The protocol logic itself — the salted-hash commitment, the expool, the two-block orchestration, the set-union agreement (`f+1` threshold; BLS-aggregatable availability proofs are specified in the design but not yet in the prototype, which counts unsigned reports), and the reservation-fee accounting — is implemented as a Go prototype with unit tests; the network simulator drives this logic to obtain the latency and bandwidth measurements.

### Figure provenance (paper figure → generating code)

- **Figure 1** (P2S workflow): hand-drawn in draw.io (lives in the paper repo, not generated by this code).
- **Figure 2** (latency, gossip-peer sweep): `plots/plot_netsim.py`, `plots/plot_netsim_sweeps.py`
- **Figure 3** (MEV totals, cumulative MEV): `plots/plot_mev_comparison.py`, `plots/plot_attack_success_cost_reward.py`
- **Figure 4** (block-stuffing duration): `plots/plot_stuffing_duration.py`
- **Figure 5** (cost vs. gain): `plots/plot_attack_success_cost_reward.py`

(The paper contains five figures; `scripts/revert_refund_design.py` produces exploratory revert-refund plots that are **not** used in the paper.)

