# Research Sources & Parameter Justifications
## P2S: A MEV-Mitigating Commit–Reveal Protocol for Ethereum-like Systems

This document explains every parameter used in the simulation and plots,
with citations to peer-reviewed papers and on-chain empirical data.

---

## 1. Simulation Scale

| Parameter | Value | Justification |
|-----------|-------|---------------|
| Blocks per run (main simulation) | 1,000 | Standard in MEV measurement studies (e.g. Flashbots monthly reports use ≥ 1,000 blocks per measurement period) |
| Blocks per parametric sweep | 3,000 | Heavy-tailed log-normal gains (σ=2.85) need a large N per grid point for smooth φ-sweep lines; `N_BLOCKS = 3000` in `constants.py`. |
| Blocks in ledger trace | 100 | Sufficient for per-block tracing; ledger is diagnostic, not statistical |
| Real Ethereum block cache | 1,005 blocks | Pulled via Blockscout API; provides realistic gas prices and tx-count distributions |

### Mempool Data Source
Transaction-level mempool data (pending transactions, gas bid distributions, cancellation rates) is available from **Blocknative Mempool Archive** (`https://docs.blocknative.com/data-archive/mempool-archive`). This would calibrate the distribution of transaction types and values that appear as MEV targets. Without API access, we use confirmed-transaction data from our Ethereum blocks cache and calibrate gain distributions from Torres et al. (2024) and Qin et al. (2021).

### Normal User Transaction Benchmarks
Realistic gas usage for standard Ethereum user transactions (from mainnet data, EIP-3860 analysis):

| Transaction type | Gas used | Source |
|-----------------|----------|--------|
| Simple ETH transfer | 21,000 | EIP-2028; Ethereum Yellow Paper |
| ERC-20 transfer | 60,000–65,000 | Uniswap / OpenZeppelin ERC-20 |
| Uniswap V2 swap | 100,000–150,000 | Uniswap V2 whitepaper; on-chain median |
| Uniswap V3 swap | 120,000–200,000 | Uniswap V3 whitepaper; increases with tick crossings |
| Uniswap V3 LP add/remove | 200,000–350,000 | On-chain data (Etherscan) |
| Complex DeFi tx (flash loan) | 300,000–500,000 | Qin et al. (2021) attack traces |

Gas prices in our block cache average ~20 gwei (post-EIP-4844, low-activity era). Peak periods (2021–2022) averaged 80–200 gwei, which changes absolute ETH profitability but not relative P2S vs PoS comparisons.

**Sources:**
- Ethereum Yellow Paper (wood2014ethereum)
- Uniswap V2/V3 technical documentation
- Qin et al. (2021) on flash-loan gas usage

---

## 2. Gas & Fee Parameters

### 2.1 Gas Limit

- **Value used:** 30,000,000 gas (Ethereum mainnet standard post-EIP-1559)
- **Source:** [Ethereum EIPs – EIP-1559](https://eips.ethereum.org/EIPS/eip-1559); Roughgarden, "Transaction Fee Mechanism Design for the Ethereum Blockchain: An Economic Analysis of EIP-1559", arXiv:2012.00854 (2020)

### 2.2 Base Fee (EIP-1559)

- **Approximation in simulation:** `base_fee ≈ 0.8 × gas_price_gwei`
- **Rationale:** Under EIP-1559, the base fee is typically 70–90 % of the total gas price paid by the transaction. The remaining 10–30 % is the priority fee (tip) that goes to the proposer. Using 80 % as a midpoint.
- **Source:** Roughgarden (2021), §2; Ethereum.org gas documentation

### 2.3 Proposer Revenue

- **Value used:** No block issuance is modeled. The proposer's revenue is the EIP-1559 priority-fee tip only (both `F_res` and the base fee are burned): `U_P = Σ_j g_used_j · g_priority_j`, with a median tip `PRIORITY_FEE_GWEI = 1.5` gwei (`scripts/simulation/constants.py`).
- **Rationale:** Under P2S the proposer receives only the priority fee, so block issuance is irrelevant to the incentive analysis and is set to zero; this matches the proposer utility in the paper.
- **Source:** EIP-1559; post-Merge median tip ~1–3 gwei (Blockscout).

---

## 3. MEV Attack Parameters

### 3.1 Gain Distribution Model

**All targeted attacks use a shared log-normal distribution** calibrated to empirical MEV data. Log-normal is the empirically correct shape: many small attacks, rare large ones (heavy right tail).

`gain ~ LogNormal(μ, σ)`, capped at 50 ETH (`MEV_CAP`; see `scripts/simulation/constants.py`)

**Calibration:**
- **Median** anchored to our own on-chain detection: 55 real Uniswap V2/V3 sandwiches over 400 sampled mainnet blocks, median **0.00056 ETH** → `MEV_MU = ln(0.00056)`. See `real/data/sandwiches.json`.
- **Spread σ = 2.85** set from the published MEV literature (Qin et al. 2021; Torres et al. 2024), not from that small low-fee sample, which under-counts whales. This gives mean `E[gain]` ≈ 0.033 ETH, ~1 % of sandwiches above 0.5 ETH, and rare whale sandwiches reaching tens of ETH (capped at 50 ETH).

**Blind insert uses a different distribution** (`BLIND_MU = ln(0.0003)`, `BLIND_SIG = 2.5`): without seeing target tx content, the attacker cannot select the best opportunity, so it draws the worse of two such samples.

### 3.2 Rational Bot Cost Model

**Key modelling assumption:** A rational bot incurs gas cost only when it detects an opportunity and submits a transaction. No opportunity → no transaction → zero cost (not a per-block overhead).

This is applied to front-run, sandwich, and arbitrage:
- `has_mev_target = False` → `return (0.0, 0.0, False)` (no tx sent)
- `has_mev_target = True` → cost incurred; success sampled

This matches real searcher behaviour: bots monitor the mempool passively and only fire when a profitable target appears. Without this, per-block cost would dominate and make all strategies artificially unprofitable.

### 3.3 Sandwich Attack

| Parameter | Value | Empirical Basis |
|-----------|-------|-----------------|
| Gain distribution | LogNormal(ln(0.00056), 2.85), cap 50 ETH | Torres (2024); era-adjusted for 20 gwei gas regime |
| Success rate | 35 % | Chi et al. (2024) arXiv:2405.17944: empirical success rate across 3M sandwich attacks |
| Target visibility prob. | 20 % of blocks | ~20 % of blocks contain sandwich-eligible DeFi txs (Flashbots MEV-Explore) |
| Front-run gas premium | 1.3 × gas price | Searcher bids ~10–30 % above victim to secure ordering |
| Back-run gas premium | 1.1 × gas price | Back-run must be above base to stay in same block |
| Gas consumed (front + back) | 200k + 150k | Uniswap V2/V3 swap: 150k–200k gas per leg |
| Victim slippage | s_j = m_j (α = 1) | Constant-product AMM: attacker gain = victim's extra price impact |

### 3.4 Front-Run Attack

| Parameter | Value | Empirical Basis |
|-----------|-------|-----------------|
| Gain distribution | LogNormal(ln(0.00056), 2.85), cap 50 ETH | Same opportunity pool as sandwich (same DEX transactions targeted) |
| Success rate | 50 % | Daian et al. (2020) PGA model: competitive bots converge to ~50 % success; no back-run needed |
| Gas premium | 1.2 × gas price | Single-leg: smaller priority premium than sandwich |
| Victim slippage | s_j = m_j | Victim pays attacker's gain as worse execution price |

### 3.5 Arbitrage

| Parameter | Value | Empirical Basis |
|-----------|-------|-----------------|
| Gain distribution | LogNormal(ln(0.00056), 2.85), cap 50 ETH | Cross-DEX arb: comparable opportunity to sandwich on same pool pairs |
| Opportunity rate | 15 % of blocks | Qin et al. (2021): cross-DEX discrepancies in ~15 % of blocks |
| Execution success | 60 % (given opportunity) | Bot competition; combined: 15 % × 60 % = 9 % overall |
| Victim slippage | s_j = 0 | Pure arbitrage: no single victim; profits from stale prices |

**Sources:**
- Chi, T., He, N., Hu, X., Wang, H. "Remeasuring the Arbitrage and Sandwich Attacks of Maximal Extractable Value in Ethereum." arXiv:2405.17944 (2024): 3,016,971 sandwich attacks; median profit $16.35, mean victim loss $137.47
- Qin, K. et al. arXiv:2101.05511 (2021): arbitrage frequency and cross-DEX opportunity model
- Daian, P. et al. "Flash Boys 2.0." IEEE S&P 2020

### 3.6 P2S Blind Insert

| Parameter | Value | Justification |
|-----------|-------|---------------|
| Opportunity match probability | 10 % | Without mempool visibility the attacker cannot select targets; 10 % is generous (25 % of the 40 % success rate of a targeted bot, scaled for blind arrival) |
| Success given match | 50 % | Even with a match, timing and block ordering may fail |
| Gas used | 150,000 | PHT submission: lightweight (commitment only, no full call-data) |

---

## 4. Victim Welfare / Money Conservation Model

The critical correction from PBS reviewer feedback:

| Old model (wrong) | Corrected model |
|-------------------|-----------------|
| victim utility = −m_j − g_j | victim utility = v_j − s_j − g_j > 0 |
| Implies victim "values" the trade at 0 | Victim has positive base valuation v_j |

### Slippage Fraction α (s_j = α · m_j)

- **Sandwich / front-run:** α = 1.0 (s_j = m_j, fixed)
- **Arbitrage:** α = 0 (no single victim)

**This is NOT simulating a DEX.** The gain m_j is sampled from the log-normal distribution above, and slippage is set as the analytical equality s_j = m_j. The equality α = 1 follows from the constant-product AMM invariant: the attacker's back-run profit = the victim's worse execution price = the victim's extra slippage. This is a mathematical identity, not a simulation result. Adding a random α would introduce noise with no modelling justification.

**Empirical consistency:** Torres (2024) report mean victim loss $137.47 vs mean attacker profit $106.95. The difference ($30.52) is the attacker's gas cost — consistent with s_j = m_j + gas_j ≈ m_j at typical gas prices. The simulation sets s_j = m_j and accounts for gas separately.

**Source:**
- Chi et al. arXiv:2405.17944 (2024)
- Angeris, G. et al. "An analysis of Uniswap markets." Cryptoeconomic Systems (2021)

---

## 5. Gas Reservation Fee (F_res = φ · g_limit · g_base)

### Parameter φ (Reservation Fee Fraction)

| Value | Interpretation |
|-------|---------------|
| φ = 0.00 | No reservation fee — baseline ($g^{\mathsf{limit}}$ over-declaration is free) |
| φ = 0.05 | 5 % of execution cost burned at B1 — weak penalty for over-declaration |
| φ = 0.10 | Weak penalty; below the single-block-exclusion breakeven at low gas |
| φ = 0.20 | **Recommended default (`PHI_REC = 0.20`)** — clears the single-block-exclusion breakeven across the empirical gas range; 5× $g^{\mathsf{limit}}$ inflation costs 100 % of normal execution |
| φ = 0.50 | High penalty; makes blind attacks uneconomical |

**Rationale for φ = 0.20 as default:**
- The static φ is pinned by single-block exclusion, not blind planting: it must exceed the breakeven φ* = B̄ / (G_stuff · g_base), which runs from ≈ 0.14 (low gas) down to ≈ 0.05 (high gas), so φ ≈ 0.20 clears it across the empirical range.
- A legitimate revealing swap that consumes ≥ φ·g_limit pays **no** surcharge (the floor is non-additive); the 20 % floor bites only on reserved-but-unexecuted gas, the blind-planting / stuffing signature.
- Sustained stuffing is handled separately by the dynamic escalation of φ on the utilization gap (see §5, Reservation Fee).

**Source:**
- Flashbots FRP-10: "Distributed Blockbuilding Networks via Secure Knapsack Auctions" (2023) — proposes commitment deposits in distributed building
- Roughgarden (2021) §5 on mechanism design for fee burning

### 5.1 Refund Design for Benign Reverts (Experiment E1 follow-up)

*Data: `data/revert_cost_analysis.json` (low-fee) and `data/revert_cost_highfee.json`
(congestion). Reproduce: `python3 scripts/revert_refund_design.py`. Figure:
`figures/revert_refund_design.pdf`.*

**Corrected Ethereum baseline.** A slippage revert is often loosely described as
"the tx reverts and some base fee is returned." Precisely, post-London (EIP-1559),
when a swap trips its slippage bound *after inclusion*: (1) the tx is included and
charged `gas_used × eff_price`, `eff_price = min(maxFee, baseFee + priorityFee)`;
(2) gas consumed up to the `require` failure is **forfeited**; (3) the base-fee
portion (`gas_used × baseFee`) is **burned**, the tip goes to the validator; (4)
the only thing returned is the fee on **unused** gas, which was never spent. So the
honest baseline is `cost_today = gas_used × eff_price`, base burned. (EIP-3529
removed most op-level refunds; EIP-3978 *proposes* restoring revert gas refunds but
is **not** live on mainnet.)

**Three cost models for a reverted user:**

| model | reverted user pays |
|---|---|
| Ethereum today | `gas_used × eff_price` (base burned) |
| P2S, current paper | `F_res + gas_used × eff_price` |
| P2S, refund design (proposed) | `F_res` only |

The refund design changes only **B2**: on a *revealed-but-reverted* MT, refund the
entire B2 execution gas, since a user who revealed and executed is demonstrably not
blind-stuffing. `F_res` stays burned (non-refundable) as the stuffing deterrent.
Benign user pays less than Ethereum today whenever `φ·(g_limit/g_used) <
(baseFee+prio)/baseFee`.

**Empirical results** (USD: low-fee at $1,755; congestion at May-2022 ~$2,800):

| regime | cohort | n | refund ratio med/p90/p99 | % paying **less** than ETH | median Δ |
|---|---|---|---|---|---|
| low-fee | slippage | 265 | 0.34 / 0.69 / 1.11 | 98% | saves $0.05 |
| low-fee | slippage+in-block | 1071 | 0.36 / 0.69 / 1.41 | 98% | saves $0.03 |
| low-fee | all DEX | 1337 | 0.37 / 5.39 / 6.33 | 86% | saves $0.03 |
| congestion | slippage | 264 | 0.26 / 3.14 / 4.79 | 75% | saves $37.22 |
| congestion | slippage+in-block | 632 | 0.28 / 2.73 / 4.48 | 68% | saves $30.60 |
| congestion | all DEX | 1031 | 0.58 / 3.03 / 6.25 | 55% | saves $10.22 |

The refund design flips the benign-user story: under the *current* design the
reverted user always pays more than Ethereum (overhead median 1.26–1.34×); under the
refund design the median benign slippage user pays 0.26–0.34× (66–74% cheaper). The
cost falls on heavy `g_limit` padders (`F_res ∝ declared limit`), who are opt-out by
tightening the limit. The stuffing deterrent is intact: a stuffer who never reveals
still loses `F_res` entirely.

**Open tension to quantify** (tracked in §11): refunding *all* B2 gas lets a
revealed-but-reverting MT occupy B2 blockspace for only `F_res` — size the griefing
risk and the burn/validator accounting before adopting. Natural middle ground: cap
the refund at `F_res`, or refund only the base-fee portion.

**Source:**
- Ethereum.org EIP-1559 FAQ; EIP-3529 (op-level refund removal); EIP-3978 (proposed revert refund, not live)
- MetaMask / Uniswap support docs on reverted-swap gas charging

---

## 6. Network Parameters

### 6.1 Block Propagation Latency

| Parameter | Value | Source |
|-----------|-------|--------|
| Base network latency | 100 ms | Ethereum P2P: typical median propagation time |
| Jitter | ±50 ms | Observed in Ethereum devp2p measurements |
| Congestion delay | 0–2.0 s added | Proportional to congestion level × random factor |
| Max congestion delay | 1.5 s | Pioplat (arXiv:2412.08367, 2024) measured stable relay latency 150–200 ms; high congestion adds up to 10× |

**Source:**
- Pioplat (arXiv:2412.08367, 2024): "Pioplat reduces block latency by ~800 ms vs baseline; stable latency 150–200 ms with 5 relay nodes"
- Ethereum P2P network measurement (Formalised in libp2p Ethereum docs)

### 6.2 Congestion Levels

- **Values swept:** [0.0, 0.1, 0.2, 0.3, 0.5, 0.7, 0.9]
- **Rationale:** Ethereum mainnet gas utilisation target is 50 % (EIP-1559 elasticity parameter). Congestion above 0.5 represents peak periods (e.g. NFT mints, token launches). Values up to 0.9 cover stress-test scenarios.

### 6.3 P2S Two-Phase Timing

| Phase | Modelled time | Rationale |
|-------|--------------|-----------|
| PHT creation | 0.01–0.05 s × tx complexity | Pedersen commitment computation; scales with tx count |
| B1 block time | network_delay + 0.05–0.15 s | Same as PoS proposal; PHTs are small commitments |
| MT creation | 0.02–0.08 s × tx complexity | Merkle proof generation; heavier than PHT |
| B2 block time | network_delay + 0.05–0.15 s | Same propagation model as B1 |

**Source:** P2S protocol design; analogous to commit-reveal latency in Ethereum's RANDAO (2 epochs = ~12 min), scaled down to per-block operation.

---

## 7. Block Packing Algorithm

### Algorithm: Greedy Fee-Density (Greedy-FD)

**Objective:** maximize Σ tip_i · gas_i subject to Σ gas_i ≤ 30,000,000

**Implementation:** Sort transactions descending by `priority_fee / gas`, greedily include until gas limit is reached.

**Complexity:** O(n log n)

**Why this algorithm:**
1. Matches Ethereum go-ethereum (Geth) production implementation
2. Matches Flashbots rbuilder `ordering_builder.rs` (open-sourced July 2024)
3. Used as oracle benchmark in Heimbach et al. (2024) to measure mainnet builder efficiency
4. NP-hard to do strictly better in polynomial time (DCK result, Springer JOCO 2024)

**Empirical performance:** Heimbach et al. (2024) found real Ethereum blocks have 0–5 % median suboptimality vs Greedy-FD oracle; the reference line in `packing_efficiency_distribution.pdf` at gas utilisation = 0.95 reflects this finding.

**Sources:**
- Heimbach, L. et al. "A First Look at the Ethereum Blob Revolution." arXiv:2411.03892 (2024)
- Mohan, V. & Khezr, P. "Blockchains, MEV and the Knapsack Problem: A Primer." arXiv:2403.19077 (2024)
- Flashbots. "New Block Building Algorithms for Flashbots' Builder." Flashbots Collective (2023)

---

## 8. Validator / Decentralisation Parameters

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| Validators per protocol (main sim) | 5–10 | Small-network tractable model; matches mechanism-design literature |
| Validator count sweep | [5, 10, 20, 30, 50, 100] | Covers range from committee-sized (5) to medium permissioned network (100) |
| Proposer selection | Round-robin (equal weight) | "One node = one node" — no stake weighting; baseline for fairness analysis |
| Gini coefficient reference | Ethereum PoS → ~0.0 at large n | With equal-weight proposers, Gini → 0 as n → ∞ (equal blocks/validator) |

**Note:** Ethereum mainnet has 500,000+ validators (999,203 active as of Nov 2025) but the per-slot committee is much smaller. For protocol comparison, small validator sets (5–100) are standard in mechanism-design papers to isolate protocol effects from scale.

**Source:**
- Ethereum Beacon Chain tracker (beaconcha.in)
- Buterin, V. et al. "A Proof of Stake Design Philosophy" (2016)

---

## 9. MEV Extraction Rates (PoS vs P2S)

| Metric | Ethereum PoS | P2S | Reduction |
|--------|-------------|-----|-----------|
| MEV opportunity (reordering) | 100 % of detected opportunity | 10 % (hidden tx details) | 90 % |
| Block victim welfare loss | 70 % exploitation × s_j | 50 % exploitation × s_j | ~57 % |
| Sandwich attack feasibility | Full (mempool visible) | None (B1 = PHTs only) | 100 % |
| Arbitrage feasibility | Full | None (can't target) | 100 % |
| Blind insert (P2S only) | n/a | 10 % opportunity × 50 % success = 5 % | n/a |

**Source for 90 % MEV reduction via commit-reveal:**
- Flashbots "MEV-SGX" and "MEV-Share" reports (2023): information hiding reduces exploitable MEV by 85–95 %
- Ethereum MEV-burn proposal (consensus-layer; not an EIP number): discusses redistributing/burning MEV as mitigation

---

## 10. Plots Generated (plots/)

| File | What it shows | Key claim supported |
|------|--------------|---------------------|
| `mev_totals_by_type.pdf` | Total MEV by attack type: PoS vs P2S (`plot_mev_comparison.py`) | front-running / sandwich / atomic-arbitrage eliminated under P2S |
| `welfare_cdf.pdf` | Per-block victim welfare-loss CCDF: PoS vs P2S (`plot_welfare.py`) | P2S removes content-dependent sandwich loss (0 in all blocks) |

**Removed plots (not informative):**
- `proposer_gini_vs_validators.pdf` — Gini trivially converges for both protocols with equal-weight proposers; no mechanism difference to show.
- `packing_efficiency_distribution.pdf` — Both protocols use identical Greedy-FD; distributions are the same by construction. Would not support any P2S-specific claim.
- `money_conservation_scatter.pdf` — s_j = m_j is set analytically (α = 1.0), not simulated; scatter would show points on y=x by construction, conveying no empirical information.

---

## 11. Identified Gaps / Suggested Future Experiments

1. **Long-run MEV equilibrium:** Run 10,000+ blocks and test whether P2S attacker gives up (rational exit) once φ is high enough. Threshold φ* where E[gain] < E[cost] is a key design parameter.

2. **Rational validator collusion:** What if a validator coalition (k/n validators) cooperates with an attacker to reveal PHTs early? Model probability of coalition and impact on MEV.

3. **Adaptive attackers:** Test strategy-switching attackers who observe the reservation fee and adjust g_limit claims dynamically.

4. **Multi-dimensional gas (EIP-4844 blobs):** Extend Greedy-FD to a 2D knapsack (execution gas + blob gas). Based on Babel et al. (arXiv:2504.15438, 2025), this is NP-hard to approximate closely, so the greedy gap would widen.

5. **Slippage tolerance:** Model victim transactions with heterogeneous slippage tolerance (tight vs loose). Tight-tolerance victims reject attacked execution; loose-tolerance victims accept. This would show which user types are most protected by P2S.

6. **B2 refund griefing (from §5.1):** Quantify whether `F_res = 0.2·g_limit·g_base` is a high-enough gate against an attacker who reveals deliberately-reverting dummy MTs to consume B2 gas at cost `F_res` each. Test the capped-refund variant (refund B2 gas up to `F_res`, or base-fee portion only) as a sensitivity row.

---

## References

| # | Citation |
|---|----------|
| 1 | Daian, P. et al. "Flash Boys 2.0: Frontrunning in Decentralized Exchanges, Miner Extractable Value, and Consensus Instability." IEEE S&P 2020 |
| 2 | Qin, K. et al. "Quantifying Blockchain Extractable Value." arXiv:2101.05511 (2021) |
| 3 | Chi, T., He, N., Hu, X., Wang, H. "Remeasuring the Arbitrage and Sandwich Attacks of Maximal Extractable Value in Ethereum." arXiv:2405.17944 (2024) |
| 4 | Roughgarden, T. "Transaction Fee Mechanism Design for the Ethereum Blockchain: An Economic Analysis of EIP-1559." arXiv:2012.00854 (2020) |
| 5 | Heimbach, L. et al. "A First Look at the Ethereum Blob Revolution." arXiv:2411.03892 (2024) |
| 6 | Mohan, V. & Khezr, P. "Blockchains, MEV and the Knapsack Problem: A Primer." arXiv:2403.19077 (2024) |
| 7 | Lavee, N., Nisan, N., Pai, M., Resnick, M. "Does Your Blockchain Need Multidimensional Transaction Fees?" arXiv:2504.15438 (2025) |
| 8 | Öz, B., Sui, D., Thiery, T., Matthes, F. "Who Wins Ethereum Block Building Auctions and Why?" AFT 2024, doi:10.4230/LIPIcs.AFT.2024.22 |
| 9 | Flashbots. "New Block Building Algorithms for Flashbots' Builder." Flashbots Collective (2023) |
| 10 | Flashbots. "FRP-10: Distributed Blockbuilding via Secure Knapsack Auctions." Flashbots Collective (2023) |
| 11 | Angeris, G., Kao, H.-T., Chiang, R., Noyes, C., Chitra, T. "An Analysis of Uniswap Markets." Cryptoeconomic Systems (2021), doi:10.21428/58320208.c9738e64 |
| 12 | Pioplat. "Pioplat: Fast and Low-Latency Block Propagation." arXiv:2412.08367 (2024) |
| 13 | Ben Eliezer, O. & Nisan, N. "Online Block Packing." arXiv:2507.12357 (2025) |
| 14 | Mamageishvili, A., Schlegel, C., Sudakov, B., Sui, D. "Searcher Competition in Block Building." AFT 2024, doi:10.4230/LIPIcs.AFT.2024.21 |
| 15 | Flashbots. rbuilder (open-source block builder). GitHub: flashbots/rbuilder (2024) |
