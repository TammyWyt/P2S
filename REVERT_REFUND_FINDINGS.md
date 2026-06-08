# Benign-user revert cost: Ethereum today vs. P2S refund design

*Experiment E1 follow-up — 2026-06-08. Data: `data/revert_cost_analysis.json`
(low-fee) and `data/revert_cost_highfee.json` (congestion). Reproduce with
`python3 scripts/revert_refund_design.py`. Figure: `figures/revert_refund_design.pdf`.*

## 1. Getting the Ethereum baseline right

A common way to describe a slippage revert is *"the transaction reverts and some
of the base fee gets returned."* That is **imprecise** and worth stating exactly,
because the whole comparison hinges on it.

What actually happens on Ethereum today (post-London / EIP-1559) when a swap
trips its slippage bound after inclusion:

1. The tx **is included in the block** and the user is charged
   `gas_used × effective_gas_price`, where
   `effective_gas_price = min(maxFee, baseFee + priorityFee)`.
2. State changes are rolled back, but the **gas consumed up to the `require`
   failure is forfeited** — it is not given back.
3. Of that charged amount, the **base-fee portion (`gas_used × baseFee`) is
   burned** permanently; the priority portion goes to the validator.
4. The only thing "returned" is the fee on the **unused** gas
   `(gas_limit − gas_used)`, which was never spent. There is **no refund of the
   base fee on the gas the revert actually consumed.**

So the honest baseline cost of a benign reverted swap is
**`cost_today = gas_used × (baseFee + priorityFee)`**, base burned. (EIP-3529
removed most operation-level refunds; EIP-3978 *proposes* restoring gas refunds
on reverts but is **not** live on mainnet.) Sources in the chat log:
ethereum.org EIP-1559 FAQ, EIP-3529, EIP-3978, MetaMask/Uniswap support docs.

## 2. The three cost models

| model | what the reverted user pays |
|---|---|
| **Ethereum today** | `gas_used × eff_price` (base burned) |
| **P2S — current paper** | `F_res + gas_used × eff_price` |
| **P2S — refund design (proposed)** | `F_res` only |

`F_res = φ · gas_limit · baseFee` (φ = 0.20), burned in **B1** and
**non-refundable** — it cannot be returned because it is already burned at
reservation time. The refund design changes only **B2**: on a *revealed-but-
reverted* MT, refund the **entire** B2 execution gas (`gas_used × eff_price`),
since a user who showed up and executed is demonstrably not blind-stuffing. The
reservation fee stays burned as the stuffing deterrent.

Ratio that matters: `refund_ratio = F_res / cost_today`. The benign user pays
**less than Ethereum today whenever** `φ·(gas_limit/gas_used) < (baseFee+prio)/baseFee`.

## 3. Empirical results

| regime | cohort | n | refund ratio (P2S/ETH) med / p90 / p99 | % who pay **less** than ETH | median Δ per revert |
|---|---|---|---|---|---|
| low-fee | slippage | 265 | 0.34 / 0.69 / 1.11 | **98%** | **saves $0.05** |
| low-fee | slippage+in-block | 1071 | 0.36 / 0.69 / 1.41 | 98% | saves $0.03 |
| low-fee | all DEX | 1337 | 0.37 / 5.39 / 6.33 | 86% | saves $0.03 |
| congestion | slippage | 264 | 0.26 / 3.14 / 4.79 | **75%** | **saves $37.22** |
| congestion | slippage+in-block | 632 | 0.28 / 2.73 / 4.48 | 68% | saves $30.60 |
| congestion | all DEX | 1031 | 0.58 / 3.03 / 6.25 | 55% | saves $10.22 |

(USD: low-fee at $1,755, congestion at the real May-2022 price ~$2,800.)

## 4. What this means

- **The refund design flips the benign-user story.** Under the *current* P2S
  design the reverted user always pays **more** than Ethereum (overhead median
  1.26–1.34×, F_res added on top). Under the refund design the **median benign
  slippage user pays far less** — 0.26–0.34× of today's cost (66–74% cheaper) —
  because `F_res` is smaller than the gas they would otherwise forfeit.
- **In congestion the saving is real money:** a benign slippage-reverted swapper
  saves a **median ~$37** per revert (pays ~$17 of `F_res` instead of ~$49 of
  burned gas), and **75%** of them come out ahead.
- **The cost falls on heavy gas-limit padders, not typical users.** `F_res ∝
  declared limit`, so the 2% (low-fee) → 25% (congestion) tail who pay more are
  the wallets that padded their limit far above consumption (`limit/used` large).
  This is mildly regressive on padding — but it is *opt-out by tightening the
  limit*, and it is strictly better than the current design for everyone below
  the parity line. See `figures/revert_refund_design.pdf`: most mass is left of
  the red line.
- **Stuffing deterrent intact.** `F_res` is still burned and non-refundable; a
  stuffer who never reveals loses it entirely. The refund only rewards
  revealed-and-executed MTs.

## 5. Open tension to quantify (not a blocker)

Refunding **all** B2 gas on a revert means a revealed-but-reverting MT occupies
B2 blockspace while paying only `F_res`. Two consequences to size before adopting:

1. **Griefing / B2 stuffing:** an attacker reveals deliberately-reverting dummy
   MTs to consume B2 gas at cost `F_res` each. Is `F_res = 0.2·limit·base` a high
   enough gate? (Stuffers must still pay it per MT and cannot reclaim it.)
2. **Burn / validator accounting:** refunded B2 base fee is no longer burned, and
   the validator does uncompensated work on reverted MTs. Minor, but state it.

A natural middle ground if the tail or griefing matters: refund B2 gas **up to
`F_res`** (cap), or refund only the base-fee portion — keep for a sensitivity row.
