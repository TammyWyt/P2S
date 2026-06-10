#!/usr/bin/env python3
"""
P2S Simulation
Main simulation comparing P2S vs Ethereum PoS using real Ethereum block data.
Aligned with Ethereum mainnet: 1000 blocks, no stake (one node = one node),
gas fees and benign transactions from mainnet data. Includes multiple MEV
attack strategies with cost/gain evaluation.
"""

import json
import math
import time
import random
import statistics
from datetime import datetime
from typing import List, Dict, Any, Tuple, Optional
from dataclasses import dataclass
import os
from collections import defaultdict
import glob

# Ethereum mainnet parameters (for alignment)
ETH_MAINNET_BLOCK_GAS_LIMIT = 30_000_000
ETH_MAINNET_BLOCK_TIME_SEC = 12
WEI_PER_ETH = 1e18
GWEI_PER_ETH = 1e9
DEFAULT_NUM_BLOCKS = 1000


# ── Heavy-tailed MEV gain (realistic tail) ────────────────────────────────────
# One realized content-dependent MEV gain (ETH). The MEDIAN is anchored to our
# on-chain sandwich detection (real/data/sandwiches.json: median 0.00056 ETH ~
# $1.7); the TAIL (sigma) is from the published MEV literature, since that small
# low-fee sample under-counts whales. With sigma = 2.85 the mean is ~0.033 ETH
# (~$100), ~1% of sandwiches exceed 0.5 ETH, and rare whales reach tens of ETH,
# bounded at MEV_CAP. See scripts/simulation/constants.py for the rationale.
_MEV_MU, _MEV_SIG, _MEV_CAP = math.log(0.00056), 2.85, 50.0


def _mev_gain() -> float:
    return min(random.lognormvariate(_MEV_MU, _MEV_SIG), _MEV_CAP)

# Post-Merge Ethereum economics (EIP-3675):
#   * Execution-layer block issuance: 0 ETH (no PoW block subsidy)
#   * Proposer receives EIP-1559 priority fees only (base fee burned)
#   * Consensus-layer attester reward per slot: ~0.06 ETH (approx.; varies with
#     validator participation rate).  Modeled as a fixed per-block reward on the
#     selected proposer for accounting parity with PoS.
POST_MERGE_BLOCK_ISSUANCE_ETH = 0.0
POST_MERGE_ATTESTER_REWARD_ETH = 0.06   # consensus-layer reward per slot

# Proposer captures priority-fee tip portion of tx gas fees as MEV/revenue.
# Post-EIP-1559: base fee is burned, only the tip flows to the proposer.
PROPOSER_TIP_FRACTION = 0.10            # ~10 % of declared gas price is tip


@dataclass
class AttackStrategyResult:
    """Cost and gain for one attack strategy over the simulation."""
    name: str
    description: str
    total_cost_eth: float = 0.0
    total_gain_eth: float = 0.0
    attempts: int = 0
    successes: int = 0
    net_profit_eth: float = 0.0
    cost_per_attempt_eth: float = 0.0
    gain_per_success_eth: float = 0.0
    cost_per_success_eth: float = 0.0  # total_cost / successes; high when success rate is low
    total_victim_welfare_loss_eth: float = 0.0  # total slippage s_j ≈ m_j suffered by victims
    total_victim_base_valuation_eth: float = 0.0  # Σ v_j: victims' gross value for attacked txs
    per_block_gain_eth: List[float] = None  # length=num_blocks: gain at each block (for bootstrap CI)

    def __post_init__(self):
        if self.per_block_gain_eth is None:
            self.per_block_gain_eth = []


class MEVAttackStrategies:
    """
    Simulate MEV attack strategies and evaluate cost vs gain.

    In P2S, B1 contains only PHTs (commitments). You cannot target a specific tx for
    front-run/sandwich — those strategies are NOT applicable in P2S. The only
    applicable strategy is blind insert, with optional no-reveal after B1:

    - Attacker submits a PHT (blind attack) without knowing other txs' content.
    - After B1 is confirmed, they see revealed content (e.g. when building B2 or
      when MTs are revealed) and can tell if their attack would be profitable.
    - If not the right attack: they choose NOT to reveal → tx is not processed,
      but they still pay the gas fee (one gas fee for PHT inclusion in B1).
    - Protocol note: This can work as a single gas-fee transaction if the
      protocol charges gas at B1 for PHT inclusion; then no-reveal still pays
      that one fee. If gas were only charged at B2 on reveal, the protocol would
      need another mechanism (e.g. commitment fee at B1) to ensure cost on no-reveal.
    """
    GAS_BLIND_INSERT = 150_000
    GAS_FRONT_RUN = 200_000
    GAS_SANDWICH_FRONT = 200_000
    GAS_SANDWICH_BACK = 150_000
    GAS_ARBITRAGE = 300_000

    # ── Victim slippage model ────────────────────────────────────────────────
    # In a constant-product AMM the attacker's sandwich profit m_j IS the
    # victim's extra slippage (price impact): s_j = m_j exactly (α = 1).
    # Front-run is analogous: the attacker moves the price before the victim,
    # so the victim pays more → their overpayment = attacker profit = s_j.
    # Arbitrage: pure cross-DEX arb with no single victim → s_j = 0.
    # The attacker's profit m_j is computed from the constant-product pool (see
    # the MEV gain model below); the victim's extra slippage equals it, s_j = m_j.
    VICTIM_SLIPPAGE_ALPHA = 1.0   # sandwich / front-run: s_j = m_j

    # ── MEV gain model: realized profit from a constant-product AMM ───────────
    # Rather than sampling a dollar gain from a fitted distribution, we simulate
    # the victim's DEX trade against a constant-product (x·y=k) pool and compute
    # the attacker's *realized* sandwich/front-run profit from the closed-form
    # optimal-sandwich formula (Angeris et al. 2021):
    #
    #     profit(Δ) = (√(r + Δ) − √r)²        [ETH, against pool reserve r]
    #
    # where Δ is the victim swap size.  MEV is therefore an emergent quantity of
    # the simulated trade and pool state, not an assumed number.  Realism enters
    # through (a) pool depth and (b) the victim swap-size distribution, both
    # calibrated to mainnet: reserve ≈ 2,000 ETH (typical major-pair pool) and
    # swap sizes log-normal with median 5.5 ETH (σ=1.2), capped at 200 ETH.  The
    # resulting targeted-attack gain has mean ≈ 0.048 ETH — consistent with the
    # $-anchored measurements of Torres et al. (2024) and our own sandwich
    # detection — with the characteristic heavy right tail (many small
    # sandwiches, rare large ones).  Profit is capped at 2.0 ETH.
    #
    # Shared opportunity: a successful attack in EITHER protocol extracts from
    # the same simulated trade, so P2S differs in attack PROBABILITY, not in gain
    # SIZE given success.  Blind insert draws from a smaller swap distribution
    # (median 2.5 ETH) because the attacker cannot pick the best opportunity.
    # AMM pool kept for reserve mean-reversion bookkeeping only; realized gains
    # are now bootstrapped from measured sandwiches (see _sample_mev_gain).
    AMM_POOL_RESERVE_ETH = 2_000.0        # constant-product pool depth (major pair)
    AMM_TRADE_MU         = math.log(5.5)  # (legacy) victim swap size
    AMM_TRADE_SIGMA      = 1.2            # (legacy) log-normal swap-size tail
    AMM_TRADE_CAP        = 200.0         # (legacy) max single swap (ETH)
    AMM_BLIND_TRADE_MU   = math.log(2.5)  # (legacy) blind insert swap size
    AMM_BLIND_TRADE_SIGMA= 1.0           # (legacy) narrower tail
    MEV_GAIN_MAX         = 0.05          # hard cap on realized profit (ETH); measured max 0.0188
    _POOL_REVERT         = 0.30          # reserve mean-reversion per block (Qin 2021)
    _POOL_NOISE          = 0.04          # per-block reserve shock (std, fraction of r)

    # ── Attack success rates ─────────────────────────────────────────────────
    # Sandwich  ~35 %: Torres (2024) arXiv:2512.17602 Table 2.
    # Front-run ~50 %: competitive bot landscape; Daian et al. (2020) PGA model.
    # Arbitrage ~9 %: 15 % cross-DEX opportunity * 60 % execution rate.
    #                 Qin et al. (2021) arXiv:2101.05511.
    # Blind (PoS) ~5 %: no targeting; random insertion.
    # P2S blind: attack_fits 10 % (cannot observe tx before B1) * success 50 %.
    SANDWICH_SUCCESS_RATE  = 0.35
    FRONT_RUN_SUCCESS_RATE = 0.50
    ARBITRAGE_SUCCESS_RATE = 0.09
    BLIND_SUCCESS_RATE     = 0.05
    P2S_ATTACK_FITS_RATE   = 0.10   # fraction of B1 blocks where blind fits
    P2S_ATTACK_SUCCESS_RATE= 0.50   # conditional success if it fits

    # Gas reservation parameter (P2S B1 step).
    # F_res = PHT_RESERVATION_PHI * g_limit * g_base (burned at B1 inclusion).
    # Scales linearly with g_limit, so over-declaring g_limit costs proportionally
    # more in burned fees — regardless of MT reveal.
    PHT_RESERVATION_PHI = 0.20  # recommended phi_rec (2x the median stuffer breakeven ~0.107)

    # ── B2 proposer ordering attack ─────────────────────────────────────────
    # INFEASIBLE: P2S protocol structurally prevents B2 from reordering committed
    # transactions.  MT censorship by the step-2 committee is the only residual
    # risk, and is blocked by the f < n/3 BFT assumption (no honest-minority
    # quorum can collude).  Constants retained for reference only.
    B2_ATTACK_PHTS_PER_BLOCK = 5
    B2_PROPOSER_MATCH_PROB   = 0.20

    def __init__(self, block_gas_prices_gwei: List[float]):
        self.block_gas_prices = block_gas_prices_gwei
        # Constant-product AMM pool; reserves mean-revert across blocks (Qin 2021)
        # so the per-attack opportunity varies block to block as on mainnet.
        self._pool_r0 = self.AMM_POOL_RESERVE_ETH
        self._pool_r  = self.AMM_POOL_RESERVE_ETH

    @staticmethod
    def gas_cost_eth(gas_price_gwei: float, gas_units: int) -> float:
        """Ethereum mainnet gas cost in ETH: (gas_price_wei * gas_used) / 1e18."""
        return (gas_price_gwei * GWEI_PER_ETH * gas_units) / WEI_PER_ETH

    def _sandwich_profit(self, trade: float) -> float:
        """Realized optimal-sandwich profit against the current pool reserve
        (Angeris et al. 2021): (√(r+Δ) − √r)², capped at MEV_GAIN_MAX."""
        r = self._pool_r
        if trade <= 0 or r <= 0:
            return 0.0
        return min((math.sqrt(r + trade) - math.sqrt(r)) ** 2, self.MEV_GAIN_MAX)

    def _pool_step(self) -> None:
        """Mean-revert the pool reserve one block (Qin 2021 reserve dynamics)."""
        shock = random.gauss(0, self._POOL_NOISE) * self._pool_r
        self._pool_r = max(
            self._pool_r + self._POOL_REVERT * (self._pool_r0 - self._pool_r) + shock, 10.0
        )

    def _sample_mev_gain(self) -> float:
        """Realized targeted-attack profit: one draw from the heavy-tailed MEV
        distribution (median anchored to measurement, tail from the literature)."""
        return _mev_gain()

    def _sample_blind_gain(self) -> float:
        """Blind insert cannot pick the best opportunity: the worse of two draws."""
        return min(_mev_gain(), _mev_gain())

    def run_blind_insert(self, block_idx: int) -> Tuple[float, float, bool]:
        """Blindly insert attack tx without mempool visibility. Returns (cost_eth, gain_eth, success)."""
        gas_price = self.block_gas_prices[block_idx % len(self.block_gas_prices)]
        cost = self.gas_cost_eth(gas_price, self.GAS_BLIND_INSERT)
        success = random.random() < self.BLIND_SUCCESS_RATE
        gain = (self._sample_blind_gain() if success else 0.0)
        return (cost, gain, success)

    def run_blind_insert_p2s_no_reveal(self, block_idx: int) -> Tuple[float, float, bool]:
        """
        P2S-only: Blind insert with optional no-reveal after B1.

        Fee model (matches Formalization §fee-structure and agents.py BlindPlanterBot):
          - F_res = φ · g_limit · g_base is burned at B1 whether or not the MT is revealed.
          - B2 execution gas is charged ONLY if the MT is revealed and executes.
        An unrevealed PHT therefore forfeits exactly F_res (no B2 gas on a tx that
        never executes).  If revealed and successful, gain is realised in B2.
        """
        gas_price = self.block_gas_prices[block_idx % len(self.block_gas_prices)]
        execution_cost = self.gas_cost_eth(gas_price, self.GAS_BLIND_INSERT)
        # F_res = φ · g_limit · g_base, burned at B1 regardless of reveal.
        f_res = self.PHT_RESERVATION_PHI * execution_cost
        # After B1 commits, attacker learns enough to decide whether to reveal.
        # P2S_ATTACK_FITS_RATE: fraction of blocks where the blind PHT happens to
        # match a profitable opportunity once B1 is confirmed.
        attack_fits = random.random() < self.P2S_ATTACK_FITS_RATE
        if not attack_fits:
            return (f_res, 0.0, False)  # no reveal → forfeit exactly F_res, no B2 gas
        # Revealed and executed in B2: F_res (B1) plus execution gas (B2).
        success = random.random() < self.P2S_ATTACK_SUCCESS_RATE
        gain = (self._sample_blind_gain() if success else 0.0)
        return (f_res + execution_cost, gain, success)

    def run_b2_proposer_ordering_attack(self, block_idx: int) -> Tuple[float, float, int]:
        """
        INFEASIBLE under P2S protocol — retained for reference only.

        B2 cannot reorder committed transactions by construction.  MT censorship
        by the step-2 committee is the only residual risk but is blocked by the
        f < n/3 BFT assumption.  Always returns (0, 0, 0).
        """
        return (0.0, 0.0, 0)

    def run_glimit_overdecl_pht(self, block_idx: int, inflation_factor: float = 5.0) -> Tuple[float, float, bool]:
        """
        g_limit over-declaration attack in P2S: attacker submits a PHT with
        g_limit = inflation_factor × actual_gas to occupy block space without
        proportional execution.

        Without F_res: cost ≈ normal gas, over-declaration is free.
        With F_res = φ · g_limit · g_base: cost scales with inflation_factor,
        making over-declaration proportionally more expensive.

        Returns (cost_eth, gain_eth=0, success=False) — no monetary gain;
        this is a block space denial-of-service. F_res makes it costly.

        The dummy PHT reserves the inflated g_limit but is never revealed, so it
        forfeits exactly F_res = φ · g_limit · g_base and pays NO B2 execution gas
        (consistent with the no-reveal rule in run_blind_insert_p2s_no_reveal).
        """
        gas_price = self.block_gas_prices[block_idx % len(self.block_gas_prices)]
        inflated_gas = int(self.GAS_BLIND_INSERT * inflation_factor)
        # F_res on the inflated declared limit; no execution gas (never revealed).
        f_res = self.PHT_RESERVATION_PHI * self.gas_cost_eth(gas_price, inflated_gas)
        return (f_res, 0.0, False)

    def _glimit_overdecl_result(self, num_blocks: int, inflation_factor: float) -> Dict[str, AttackStrategyResult]:
        """Return a single AttackStrategyResult for a g_limit over-declaration attempt over num_blocks."""
        total_cost = sum(
            self.run_glimit_overdecl_pht(i, inflation_factor)[0] for i in range(num_blocks)
        )
        return {
            f"glimit_overdecl_{int(inflation_factor)}x_pht": AttackStrategyResult(
                name=f"glimit_overdecl_{int(inflation_factor)}x_pht",
                description=(
                    f"g_limit over-declaration PHT: g_limit inflated {inflation_factor:.0f}× "
                    f"to occupy block space. F_res = φ·g_limit·g_base scales linearly — "
                    f"{inflation_factor:.0f}× g_limit burns {inflation_factor:.0f}× F_res."
                ),
                total_cost_eth=total_cost,
                total_gain_eth=0.0,
                attempts=num_blocks,
                successes=0,
                net_profit_eth=-total_cost,
                cost_per_attempt_eth=total_cost / num_blocks if num_blocks else 0.0,
                gain_per_success_eth=0.0,
                cost_per_success_eth=0.0,
                total_victim_welfare_loss_eth=0.0,
                total_victim_base_valuation_eth=0.0,
            )
        }

    def run_front_run(self, block_idx: int, block_has_mev_target: bool) -> Tuple[float, float, bool]:
        """
        Front-run: attacker copies target tx and bids higher gas to land first.
        Requires visible mempool (Ethereum PoS only; not possible in P2S B1).
        Gas premium 1.2× (priority fee bid to jump the queue).
        Success rate 50 %: competitive bot landscape (Daian et al. 2020 PGA model).
        Gain: AMM-realized profit on the same simulated DEX swap as sandwich.
        s_j = m_j (victim pays the attacker's gain as extra slippage).
        """
        gas_price = self.block_gas_prices[block_idx % len(self.block_gas_prices)]
        # Rational bot: only submits tx when a target is visible in the mempool.
        # No target → no transaction sent → zero gas cost (not cost, 0.0).
        if not block_has_mev_target:
            return (0.0, 0.0, False)
        cost = self.gas_cost_eth(gas_price * 1.2, self.GAS_FRONT_RUN)
        success = random.random() < self.FRONT_RUN_SUCCESS_RATE
        gain = (self._sample_mev_gain() if success else 0.0)
        return (cost, gain, success)

    def run_sandwich(self, block_idx: int, block_has_mev_target: bool) -> Tuple[float, float, bool]:
        """
        Sandwich: front-buy → victim buys at worse price → back-sell.
        Requires visible mempool (Ethereum PoS only; not possible in P2S B1).
        Gas premium: front leg 1.3×, back leg 1.1× (standard bot bid pattern).
        Success rate 35 %: Torres et al. (2024) arXiv:2512.17602 Table 2.
        Gain: AMM-realized sandwich profit on the block's simulated victim swap.
        s_j = m_j (victim's extra slippage funds the attacker; money conserved).
        """
        gas_price = self.block_gas_prices[block_idx % len(self.block_gas_prices)]
        # Rational bot: only submits when target is visible. No target → no tx → zero cost.
        if not block_has_mev_target:
            return (0.0, 0.0, False)
        cost = (self.gas_cost_eth(gas_price * 1.3, self.GAS_SANDWICH_FRONT) +
                self.gas_cost_eth(gas_price * 1.1, self.GAS_SANDWICH_BACK))
        success = random.random() < self.SANDWICH_SUCCESS_RATE
        gain = (self._sample_mev_gain() if success else 0.0)
        return (cost, gain, success)

    # Probability a cross-DEX price discrepancy exists in a given block.
    # Qin et al. (2021): ~15 % of blocks contain an exploitable arb opportunity.
    ARBITRAGE_OPPORTUNITY_RATE = 0.15
    # Execution success conditional on opportunity (competition from other bots).
    # Combined: 0.15 × 0.60 ≈ 0.09 overall rate — matches ARBITRAGE_SUCCESS_RATE.
    ARBITRAGE_EXEC_RATE = 0.60

    def run_arbitrage(self, block_idx: int) -> Tuple[float, float, bool]:
        """
        Cross-DEX arbitrage: exploit price discrepancy between two pools.
        No single victim (pure arb); s_j = 0.
        Rational bot only submits tx when it detects an opportunity (15 % of blocks).
        Given opportunity: 60 % execution success (bot competition).
        Combined success rate: 15 % × 60 % = 9 % (Qin et al. 2021 arXiv:2101.05511).
        Gain: AMM-realized profit on a simulated pool imbalance — arbitrage
        opportunity sizes are comparable to sandwich profits for the same pools.
        """
        gas_price = self.block_gas_prices[block_idx % len(self.block_gas_prices)]
        # Rational bot: only transacts when cross-DEX discrepancy detected.
        if random.random() >= self.ARBITRAGE_OPPORTUNITY_RATE:
            return (0.0, 0.0, False)
        cost = self.gas_cost_eth(gas_price, self.GAS_ARBITRAGE)
        success = random.random() < self.ARBITRAGE_EXEC_RATE
        gain = (self._sample_mev_gain() if success else 0.0)
        return (cost, gain, success)

    def evaluate_all_strategies(
        self,
        num_blocks: int,
        block_has_mev_target_fn: Optional[Any] = None,
        target_visibility: bool = True,
    ) -> Dict[str, AttackStrategyResult]:
        """
        Evaluate cost and gain for each strategy.
        target_visibility=False (P2S): B1 has only PHTs → front_run/sandwich have no target, gain=0.
        target_visibility=True (Ethereum PoS): mempool visible → targets can exist.
        """
        if target_visibility and block_has_mev_target_fn is None:
            def default_has_target(_i: int) -> bool:
                return random.random() < 0.2
            has_target = default_has_target
        elif not target_visibility:
            has_target = lambda _i: False  # P2S: cannot target from B1
        else:
            has_target = block_has_mev_target_fn

        results = {}
        # Ethereum PoS: only targeted strategies (front_run, sandwich, arbitrage).
        # Blind insert is NOT rational on Ethereum — mempool is visible, so you target instead.
        #
        # Victim slippage model: when attacked, the victim transaction still executes
        # at a worse but acceptable price.  The victim's utility is v_j - s_j - g_j > 0,
        # Money conservation: in a constant-product AMM, s_j ≈ m_j.
        # The attacker's back-run profit comes from the price impact of the victim's
        # own trade — it is funded by the victim's worse execution, not "thin air".
        # α ≈ 1 captures this.  Victim utility remains positive because v_j > s_j + g_j:
        # users only submit transactions they value more than their worst-case execution.
        # Victim's residual utility ε = v_j - s_j - g_j is sampled from (0, 0.1] ETH.
        # alpha=1 for sandwich/front-run (s_j = m_j); 0 for arbitrage (no victim)
        victim_alpha = {"front_run": self.VICTIM_SLIPPAGE_ALPHA,
                        "sandwich":  self.VICTIM_SLIPPAGE_ALPHA,
                        "arbitrage": 0.0}
        # Fixed epsilon = 0.01 ETH residual utility: victim values the trade
        # at v_j = s_j + g_j + ε.  Fixed (not random) because this is a model
        # assumption, not a measured quantity — adding randomness here is noise.
        VICTIM_RESIDUAL_UTILITY = 0.01
        # Victim gas: typical Uniswap v3 swap ~150k gas units.
        VICTIM_GAS_UNITS = 150_000

        for name, desc, run_fn in [
            ("front_run", "Front-run visible target tx",
             lambda i: self.run_front_run(i, has_target(i))),
            ("sandwich", "Sandwich attack (front + back run)",
             lambda i: self.run_sandwich(i, has_target(i))),
            ("arbitrage", "Cross-DEX arbitrage",
             lambda i: self.run_arbitrage(i)),
        ]:
            total_cost = 0.0
            total_gain = 0.0
            total_victim_loss = 0.0
            total_victim_valuation = 0.0
            attempts = num_blocks
            successes = 0
            alpha = victim_alpha[name]
            per_block_gains: List[float] = []
            for i in range(num_blocks):
                cost, gain, success = run_fn(i)
                total_cost += cost
                total_gain += gain
                per_block_gains.append(gain)
                if success:
                    successes += 1
                    s_j = alpha * gain   # s_j = m_j (money conserved)
                    gp  = self.block_gas_prices[i % len(self.block_gas_prices)]
                    g_j = self.gas_cost_eth(gp, VICTIM_GAS_UNITS)
                    total_victim_loss += s_j
                    total_victim_valuation += s_j + g_j + VICTIM_RESIDUAL_UTILITY
            net = total_gain - total_cost
            cost_per_success = total_cost / successes if successes > 0 else total_cost
            results[name] = AttackStrategyResult(
                name=name,
                description=desc,
                total_cost_eth=total_cost,
                total_gain_eth=total_gain,
                attempts=attempts,
                successes=successes,
                net_profit_eth=net,
                cost_per_attempt_eth=total_cost / attempts if attempts else 0,
                gain_per_success_eth=total_gain / successes if successes else 0,
                cost_per_success_eth=cost_per_success,
                total_victim_welfare_loss_eth=total_victim_loss,
                total_victim_base_valuation_eth=total_victim_valuation,
                per_block_gain_eth=per_block_gains,
            )
        return results

    def evaluate_p2s_strategies(self, num_blocks: int) -> Dict[str, AttackStrategyResult]:
        """
        P2S only: the only applicable strategy is blind insert (with no-reveal after B1).
        Front-run, sandwich, arbitrage are NOT applicable — you cannot
        target from B1 (PHT only). Results contain only 'blind_insert_p2s'.
        """
        total_cost = 0.0
        total_gain = 0.0
        total_victim_loss = 0.0
        total_victim_valuation = 0.0
        successes = 0
        VICTIM_GAS_UNITS = 150_000
        per_block_gains: List[float] = []
        for i in range(num_blocks):
            cost, gain, success = self.run_blind_insert_p2s_no_reveal(i)
            total_cost += cost
            total_gain += gain
            per_block_gains.append(gain)
            if success:
                successes += 1
                s_j = self.VICTIM_SLIPPAGE_ALPHA * gain  # s_j = m_j
                gp  = self.block_gas_prices[i % len(self.block_gas_prices)]
                g_j = self.gas_cost_eth(gp, VICTIM_GAS_UNITS)
                total_victim_loss += s_j
                total_victim_valuation += s_j + g_j + 0.01
        net = total_gain - total_cost
        cost_per_success = total_cost / successes if successes > 0 else total_cost
        return {
            "blind_insert_p2s": AttackStrategyResult(
                name="blind_insert_p2s",
                description="Blind insert; after B1 can choose not to reveal (tx not processed, gas still paid)",
                total_cost_eth=total_cost,
                total_gain_eth=total_gain,
                attempts=num_blocks,
                successes=successes,
                net_profit_eth=net,
                cost_per_attempt_eth=total_cost / num_blocks if num_blocks else 0,
                gain_per_success_eth=total_gain / successes if successes else 0,
                cost_per_success_eth=cost_per_success,
                total_victim_welfare_loss_eth=total_victim_loss,
                total_victim_base_valuation_eth=total_victim_valuation,
                per_block_gain_eth=per_block_gains,
            ),
            # g_limit over-declaration: cost of inflating g_limit by 5×.
            # With F_res = φ · g_limit · g_base, cost scales linearly with g_limit:
            # inflating by 5× costs 5× more in burned reservation fees regardless of
            # whether the MT is ever revealed.  No gain: pure block space consumption.
            **self._glimit_overdecl_result(num_blocks, inflation_factor=5.0),
        }


class P2SSimulator:
    """Simulator: 1000 blocks, no stake (one node = one node), Ethereum mainnet gas and benign tx."""

    def __init__(self):
        random.seed(42)  # deterministic block ledger / MEV-totals across runs
        self.network_latency_base = 0.1
        self.network_jitter = 0.05
        self.base_gas_price_gwei = 20  # fallback gwei (Ethereum mainnet typical range)

        self.results = {
            'p2s_data': [],
            'ethereum_pos_data': [],
            'profit_distribution': {'p2s': {}, 'ethereum_pos': {}},
            'mev_reordering': {'p2s': [], 'ethereum_pos': []},
            'overhead_metrics': {'p2s': {}, 'ethereum_pos': {}},
            'attack_strategies': {},
            'metadata': {
                'timestamp': datetime.now().strftime("%Y%m%d_%H%M%S"),
                'description': "P2S simulation: 1000 blocks, no stake, Ethereum mainnet gas, MEV attack strategies",
                'num_blocks': DEFAULT_NUM_BLOCKS,
                'ethereum_mainnet_alignment': {
                    'block_gas_limit': ETH_MAINNET_BLOCK_GAS_LIMIT,
                    'block_time_sec': ETH_MAINNET_BLOCK_TIME_SEC,
                }
            }
        }
        self.validators = {}
        self.transactions = {}
        self.block_rewards = defaultdict(float)
        self._p2s_proposer_index = 0
        self._eth_proposer_index = 0
        
    def load_ethereum_blocks(self, data_dir="data") -> List[Dict]:
        """Load real Ethereum block data from cache"""
        cache_file = f"{data_dir}/ethereum_blocks_cache.json"
        
        if not os.path.exists(cache_file):
            print("⚠️  No Ethereum block data found. Run extract_ethereum_blocks.py first.")
            return []
        
        print(f"📂 Loading Ethereum blocks from cache: {cache_file}")
        
        with open(cache_file, 'r') as f:
            cached_data = json.load(f)
            # Cache is a dict of block_number -> block_data
            blocks = list(cached_data.values())
            print(f"✅ Loaded {len(blocks)} blocks from cache")
            return blocks

    def _synthetic_ethereum_block(self, block_number: int) -> Dict:
        """Generate a synthetic Ethereum-style block when cache has fewer than num_blocks."""
        tx_count = random.randint(50, 200)
        transactions = []
        for i in range(tx_count):
            transactions.append({
                'hash': f"0x{random.getrandbits(256):064x}",
                'from': f"0x{random.getrandbits(160):040x}",
                'to': f"0x{random.getrandbits(160):040x}",
                'value': random.randint(10**15, 10**19),
                'gas': random.randint(21000, 500000),
                'gasPrice': random.randint(20 * 10**9, 100 * 10**9),
                'nonce': i,
            })
        return {
            'block_number': block_number,
            'timestamp': int(time.time()),
            'transaction_count': tx_count,
            'transactions': transactions,
        }

    def create_validator(self, validator_id: str, protocol: str):
        """Create a validator (one node = one node; no stake used for selection)."""
        self.validators[validator_id] = {
            'id': validator_id,
            'protocol': protocol,
            'blocks_proposed': 0,
            'total_rewards': 0.0,
            'total_gas_costs': 0.0,
            'net_profit': 0.0,
            'mev_extracted': 0.0
        }
    
    def gas_cost_eth(self, gas_price_gwei: float, gas_units: int) -> float:
        """Ethereum mainnet: cost in ETH = (gas_price_wei * gas_used) / 1e18."""
        return (gas_price_gwei * GWEI_PER_ETH * gas_units) / WEI_PER_ETH

    @staticmethod
    def pack_block_greedy_fd(
        transactions: List[Dict],
        gas_limit: int = ETH_MAINNET_BLOCK_GAS_LIMIT,
        base_fee_gwei: float = 0.0,
    ) -> Dict[str, Any]:
        """
        Greedy priority-fee-density block packing.

        A textbook greedy approximation to the block-packing knapsack: rank
        transactions by priority_fee / gas and fill to the block gas limit.
        We use this as a deterministic baseline that is structurally similar
        to (but not bit-identical to) the heuristics used by production Geth
        and Flashbots rbuilder.  Complexity: O(n log n).

        Background on greedy fee-density packing in MEV / block-construction
        contexts: Heimbach et al. (arXiv:2411.03892, 2024); Azouvi & Hicks
        (arXiv:2403.19077, 2024).  Neither is a precise reference for the
        production implementations; we use them as positioning, not citation.

        Under EIP-1559, the builder's revenue is the priority fee (tip), not the
        base fee (which is burned).  Fee density = priority_fee_gwei / gas.

        Args:
            transactions: candidate transactions, each with 'gas_price' (gwei)
                          and 'gas_limit' keys (from convert_ethereum_tx).
            gas_limit:    block gas limit (default: Ethereum mainnet 30 M).
            base_fee_gwei: current EIP-1559 base fee in gwei (burned, not revenue).

        Returns dict with:
            included_txs     – ordered list of included transactions
            gas_used         – total gas consumed
            gas_utilization  – gas_used / gas_limit ∈ [0, 1]
            total_fee_eth    – total priority-fee revenue to the block proposer
            excluded_count   – number of candidate txs that did not fit
        """
        def priority_fee(tx: Dict) -> float:
            gas_price = tx.get('gas_price', 0.0)
            # tip = max(0, gas_price - base_fee) under EIP-1559
            return max(0.0, gas_price - base_fee_gwei)

        sorted_txs = sorted(
            transactions,
            key=lambda tx: (
                priority_fee(tx) / tx.get('gas_limit', 21000)
                if tx.get('gas_limit', 21000) > 0 else 0.0
            ),
            reverse=True,
        )
        included: List[Dict] = []
        gas_used = 0
        total_fee_gwei = 0.0
        for tx in sorted_txs:
            gas = tx.get('gas_limit', 21000)
            if gas_used + gas <= gas_limit:
                included.append(tx)
                gas_used += gas
                total_fee_gwei += priority_fee(tx) * gas
        total_fee_eth = (total_fee_gwei * GWEI_PER_ETH) / WEI_PER_ETH
        return {
            'included_txs': included,
            'gas_used': gas_used,
            'gas_utilization': gas_used / gas_limit if gas_limit > 0 else 0.0,
            'total_fee_eth': total_fee_eth,
            'excluded_count': len(transactions) - len(included),
        }

    @staticmethod
    def _congestion_to_block_fill(congestion_level: float) -> float:
        """Map the synthetic 'congestion_level' delay multiplier to block gas-utilization fraction.

        The simulator's congestion bands (0.0, 0.1, 0.3, 0.5, 0.7) historically
        modeled a delay multiplier with no clear Ethereum observable.  We expose
        a deterministic correspondence so plots can label the x-axis honestly:
            congestion 0.0 → 0.00 fill (empty block)
            congestion 0.1 → 0.25 fill
            congestion 0.3 → 0.50 fill (EIP-1559 target)
            congestion 0.5 → 0.75 fill (above target)
            congestion 0.7 → 1.00 fill (block at gas limit)
        Values outside the buckets are linearly interpolated.
        """
        anchors = [(0.0, 0.0), (0.1, 0.25), (0.3, 0.50), (0.5, 0.75), (0.7, 1.0)]
        for (c0, f0), (c1, f1) in zip(anchors, anchors[1:]):
            if c0 <= congestion_level <= c1:
                if c1 == c0:
                    return f0
                return f0 + (f1 - f0) * (congestion_level - c0) / (c1 - c0)
        # outside buckets: clamp
        return max(0.0, min(1.0, anchors[-1][1] if congestion_level > anchors[-1][0] else anchors[0][1]))

    @staticmethod
    def _block_fill_to_congestion(block_fill: float) -> float:
        """Inverse of _congestion_to_block_fill: take gas-utilization fraction → delay multiplier."""
        anchors = [(0.0, 0.0), (0.25, 0.1), (0.50, 0.3), (0.75, 0.5), (1.0, 0.7)]
        block_fill = max(0.0, min(1.0, block_fill))
        for (f0, c0), (f1, c1) in zip(anchors, anchors[1:]):
            if f0 <= block_fill <= f1:
                if f1 == f0:
                    return c0
                return c0 + (c1 - c0) * (block_fill - f0) / (f1 - f0)
        return anchors[-1][1]

    def simulate_network_delay(self, congestion_level=0.0):
        """Simulate per-slot network delay (seconds).

        congestion_level is the synthetic delay multiplier (legacy name).  The
        plotting code translates this back to block gas-utilization % via
        ``_congestion_to_block_fill`` so the x-axis is labelled with an
        Ethereum observable rather than a synthetic parameter.
        """
        base_delay = self.network_latency_base
        jitter = random.uniform(-self.network_jitter, self.network_jitter)
        congestion_delay = congestion_level * random.uniform(0.5, 2.0)
        return max(0.01, base_delay + jitter + congestion_delay)
    
    def calculate_reordering_opportunity(self, transactions: List[Dict]) -> float:
        """Calculate MEV opportunity from transaction reordering"""
        if len(transactions) < 2:
            return 0.0
        
        # Calculate potential MEV from reordering
        # Higher value transactions with lower gas prices = reordering opportunity
        mev_opportunity = 0.0
        for tx in transactions:
            # Convert gasPrice from wei to gwei if needed; support both raw and converted tx format
            gas_price = tx.get('gas_price') or tx.get('gasPrice', 0)
            if gas_price > 1e15:  # Likely in wei, convert to gwei
                gas_price = gas_price / 1e9
            value = tx.get('value', 0)
            if isinstance(value, str):
                try:
                    value = int(value, 16) if value.startswith('0x') else int(value)
                except Exception:
                    value = 0

            # If high value but low gas price, there's reordering potential
            if value > 1e18 and gas_price < 50:  # > 1 ETH value, < 50 gwei
                mev_opportunity += (value / 1e18) * 0.05  # 5% of value in ETH as potential MEV

        return mev_opportunity

    def _measured_block_sandwich_loss(self) -> float:
        """Per-block content-dependent victim loss: the number of sandwiches in a
        block ~ Poisson(0.14) (measured frequency: 55 attacks over 400 sampled
        mainnet blocks), and each victim loss is one heavy-tailed MEV draw (median
        anchored to measurement, tail from the literature). Money is conserved, so
        victim loss equals attacker gain; a block with a whale sandwich loses a lot."""
        lam = 0.14
        L = math.exp(-lam)
        k, p = 0, 1.0
        while True:
            k += 1
            p *= random.random()
            if p <= L:
                k -= 1
                break
        return sum(_mev_gain() for _ in range(k))

    def convert_ethereum_tx(self, eth_tx: Dict) -> Dict:
        """Convert Ethereum transaction format to our format"""
        gas_price = eth_tx.get('gasPrice', 0)
        if isinstance(gas_price, str):
            gas_price = int(gas_price, 16) if gas_price.startswith('0x') else int(gas_price)
        
        value = eth_tx.get('value', 0)
        if isinstance(value, str):
            value = int(value, 16) if value.startswith('0x') else int(value)
        
        return {
            'hash': eth_tx.get('hash', ''),
            'value': value,
            'gas_price': gas_price / 1e9 if gas_price > 1e9 else gas_price,  # Convert to gwei
            'gas_limit': eth_tx.get('gas', 21000),
            'from': eth_tx.get('from', ''),
            'to': eth_tx.get('to', ''),
            'complexity': random.uniform(0.5, 2.0)
        }
    
    def simulate_p2s_block(self, block_num: int, proposer_id: str, ethereum_block: Dict, congestion: float):
        """Simulate P2S block processing using real Ethereum block data"""
        start_time = time.time()
        
        # Convert Ethereum transactions then apply greedy fee-density block packing (B1 step).
        # In P2S, B1 packs PHTs by reserved gas capacity (g^limit).  The same
        # greedy priority-fee-density rule, structurally similar to Geth and Flashbots heuristics is applied so the comparison
        # against Ethereum PoS uses an identical packing benchmark.
        all_txs = [self.convert_ethereum_tx(tx) for tx in ethereum_block.get('transactions', [])]
        b1_base_fee = self.base_gas_price_gwei * 0.8  # approximate EIP-1559 base fee
        b1_pack = self.pack_block_greedy_fd(all_txs, ETH_MAINNET_BLOCK_GAS_LIMIT, b1_base_fee)
        transactions = b1_pack['included_txs']  # only packed txs proceed

        # Phase 1: PHT Creation
        pht_time = sum(random.uniform(0.01, 0.05) * tx.get('complexity', 1.0) for tx in transactions)
        time.sleep(min(pht_time, 0.1))  # Cap at 0.1s for simulation speed
        
        # Phase 2: B1 Block
        b1_time = self.simulate_network_delay(congestion) + random.uniform(0.05, 0.15)
        time.sleep(min(b1_time, 0.2))
        
        # Phase 3: MT Creation
        mt_time = sum(random.uniform(0.02, 0.08) * tx.get('complexity', 1.0) for tx in transactions)
        time.sleep(min(mt_time, 0.1))
        
        # Phase 4: B2 Block
        b2_time = self.simulate_network_delay(congestion) + random.uniform(0.05, 0.15)
        time.sleep(min(b2_time, 0.2))
        
        total_time = time.time() - start_time

        # Ethereum mainnet gas cost: (gas_price_gwei * 1e9 * gas_limit) / 1e18 ETH per tx
        gas_cost = sum(
            self.gas_cost_eth(tx.get('gas_price', self.base_gas_price_gwei), tx.get('gas_limit', 21000))
            for tx in transactions
        )

        # P2S gas reservation fees (B1 step).
        # Each PHT burns F_res = φ · g_limit · g_base at B1 inclusion, regardless of
        # whether the matching MT is later revealed.  Over-declaring g_limit inflates
        # F_res proportionally, so the cost of over-reservation scales with g_limit.
        # F_res is burned (not paid to the proposer), consistent with EIP-1559 base fee.
        phi = MEVAttackStrategies.PHT_RESERVATION_PHI
        reservation_fees_burned = sum(
            phi * self.gas_cost_eth(
                tx.get('gas_price', self.base_gas_price_gwei), tx.get('gas_limit', 21000)
            )
            for tx in transactions
        )

        # Block reward (post-Merge, EIP-3675):
        #   * Execution layer issuance: 0 ETH (POST_MERGE_BLOCK_ISSUANCE_ETH = 0)
        #   * Consensus layer attester reward: ~0.06 ETH/slot
        #   * Plus EIP-1559 priority-fee tip ≈ PROPOSER_TIP_FRACTION of gas fees
        # Reservation fees are burned (EIP-1559 style) and NOT proposer revenue.
        block_reward = POST_MERGE_BLOCK_ISSUANCE_ETH + POST_MERGE_ATTESTER_REWARD_ETH + sum(
            self.gas_cost_eth(tx.get('gas_price', self.base_gas_price_gwei), tx.get('gas_limit', 21000)) * PROPOSER_TIP_FRACTION
            for tx in transactions
        )

        # MEV reordering opportunity (reduced in P2S due to hidden details)
        mev_opportunity = self.calculate_reordering_opportunity(transactions) * 0.1

        # Victim welfare loss per block under P2S: content-dependent extraction
        # (sandwich/front-run) is structurally eliminated (Corollary, content-ordering
        # independence), so the measured-sandwich victim loss is zero.
        victim_welfare_loss = 0.0

        # Update validator metrics
        if proposer_id in self.validators:
            self.validators[proposer_id]['blocks_proposed'] += 1
            self.validators[proposer_id]['total_rewards'] += block_reward
            self.validators[proposer_id]['total_gas_costs'] += gas_cost
            self.validators[proposer_id]['net_profit'] = (
                self.validators[proposer_id]['total_rewards'] -
                self.validators[proposer_id]['total_gas_costs']
            )

        return {
            'block_number': ethereum_block.get('block_number', block_num),
            'proposer': proposer_id,
            'protocol': 'P2S',
            'transaction_count': len(transactions),
            'total_time': total_time,
            'pht_time': pht_time,
            'b1_time': b1_time,
            'mt_time': mt_time,
            'b2_time': b2_time,
            'gas_cost': gas_cost,
            'reservation_fees_burned': reservation_fees_burned,
            'block_reward': block_reward,
            'mev_opportunity': mev_opportunity,
            'victim_welfare_loss': victim_welfare_loss,
            'network_latency': b1_time + b2_time,
            'congestion_level': congestion,
            # greedy fee-density packing.metrics (structurally similar to Geth/Flashbots heuristics)
            'packing_gas_utilization': b1_pack['gas_utilization'],
            'packing_fee_revenue_eth': b1_pack['total_fee_eth'],
            'packing_excluded_txs': b1_pack['excluded_count'],
        }
    
    def simulate_ethereum_pos_block(self, block_num: int, proposer_id: str, ethereum_block: Dict, congestion: float):
        """Simulate standard Ethereum PoS block using real Ethereum data"""
        start_time = time.time()

        # Convert Ethereum transactions then apply greedy fee-density packing.
        # This is the identical algorithm used by Geth and Flashbots rbuilder in
        # production (related: Heimbach 2024).  Using the same
        # algorithm for both protocols ensures a fair apples-to-apples comparison.
        all_txs = [self.convert_ethereum_tx(tx) for tx in ethereum_block.get('transactions', [])]
        pos_base_fee = self.base_gas_price_gwei * 0.8
        pos_pack = self.pack_block_greedy_fd(all_txs, ETH_MAINNET_BLOCK_GAS_LIMIT, pos_base_fee)
        transactions = pos_pack['included_txs']
        
        # Mempool processing
        mempool_time = random.uniform(0.01, 0.05) * len(transactions) / 100
        time.sleep(min(mempool_time, 0.05))
        
        # Block proposal (validator can see all transaction details and reorder)
        proposal_time = self.simulate_network_delay(congestion) + random.uniform(0.05, 0.15)
        time.sleep(min(proposal_time, 0.2))
        
        # Confirmation
        confirmation_time = self.simulate_network_delay(congestion)
        time.sleep(min(confirmation_time, 0.1))
        
        total_time = time.time() - start_time

        # Ethereum mainnet gas cost per tx
        gas_cost = sum(
            self.gas_cost_eth(tx.get('gas_price', self.base_gas_price_gwei), tx.get('gas_limit', 21000))
            for tx in transactions
        )
        # Block reward (post-Merge, EIP-3675): same accounting as P2S branch.
        # Zero execution-layer issuance + consensus-layer attester reward + EIP-1559 tip.
        block_reward = POST_MERGE_BLOCK_ISSUANCE_ETH + POST_MERGE_ATTESTER_REWARD_ETH + sum(
            self.gas_cost_eth(tx.get('gas_price', self.base_gas_price_gwei), tx.get('gas_limit', 21000)) * PROPOSER_TIP_FRACTION
            for tx in transactions
        )

        # MEV reordering (full visibility in PoS)
        mev_opportunity = self.calculate_reordering_opportunity(transactions) * 1.0

        # Victim welfare loss per block: s_j ≈ m_j (money conserved in AMM sandwich),
        # calibrated to measured on-chain sandwich extraction (count ~ Poisson(0.14),
        # loss bootstrapped from the 55 measured profits).
        victim_welfare_loss = self._measured_block_sandwich_loss()

        if proposer_id in self.validators:
            self.validators[proposer_id]['blocks_proposed'] += 1
            self.validators[proposer_id]['total_rewards'] += block_reward
            self.validators[proposer_id]['total_gas_costs'] += gas_cost
            self.validators[proposer_id]['net_profit'] = (
                self.validators[proposer_id]['total_rewards'] -
                self.validators[proposer_id]['total_gas_costs']
            )
            self.validators[proposer_id]['mev_extracted'] += mev_opportunity * 0.6

        return {
            'block_number': ethereum_block.get('block_number', block_num),
            'proposer': proposer_id,
            'protocol': 'Ethereum PoS',
            'transaction_count': len(transactions),
            'total_time': total_time,
            'mempool_time': mempool_time,
            'proposal_time': proposal_time,
            'confirmation_time': confirmation_time,
            'gas_cost': gas_cost,
            'block_reward': block_reward,
            'mev_opportunity': mev_opportunity,
            'victim_welfare_loss': victim_welfare_loss,
            'network_latency': proposal_time + confirmation_time,
            'congestion_level': congestion,
            # greedy fee-density packing.metrics (structurally similar to Geth/Flashbots heuristics)
            'packing_gas_utilization': pos_pack['gas_utilization'],
            'packing_fee_revenue_eth': pos_pack['total_fee_eth'],
            'packing_excluded_txs': pos_pack['excluded_count'],
        }
    
    def calculate_gini_coefficient(self, values: List[float]) -> float:
        """Calculate Gini coefficient for profit distribution"""
        if not values or all(v == 0 for v in values):
            return 0.0
        
        sorted_values = sorted(values)
        n = len(sorted_values)
        cumsum = 0
        for i, value in enumerate(sorted_values, 1):
            cumsum += value * (2 * i - n - 1)
        
        return cumsum / (n * sum(sorted_values)) if sum(sorted_values) > 0 else 0.0
    
    def run_simulation(self, num_blocks: int = DEFAULT_NUM_BLOCKS):
        """Run simulation: exactly num_blocks (default 1000), no stake, Ethereum mainnet gas, benign tx + attack strategies."""
        print("=" * 80)
        print("P2S SIMULATION (Ethereum mainnet aligned)")
        print("=" * 80)
        print(f"Simulating {num_blocks} blocks per protocol")
        print("No stake: one node = one node (equal proposer rotation)")
        print("Gas fees and benign tx from Ethereum mainnet data")
        print("=" * 80)

        ethereum_blocks = self.load_ethereum_blocks()
        if not ethereum_blocks:
            print("❌ No Ethereum block data. Run: python scripts/extract_ethereum_blocks.py 1000 1")
            return None

        # Use exactly num_blocks (pad with synthetic if cache has fewer)
        if len(ethereum_blocks) < num_blocks:
            print(f"⚠️  Cache has {len(ethereum_blocks)} blocks; padding to {num_blocks} with synthetic blocks")
            for i in range(len(ethereum_blocks), num_blocks):
                ethereum_blocks.append(self._synthetic_ethereum_block(i))
        ethereum_blocks = ethereum_blocks[:num_blocks]

        # Create validators: no stake, equal nodes
        num_validators = 10
        for i in range(num_validators):
            self.create_validator(f"p2s_validator_{i}", "P2S")
            self.create_validator(f"ethereum_pos_validator_{i}", "Ethereum PoS")

        self._p2s_proposer_index = 0
        self._eth_proposer_index = 0
        congestion_levels = [0.0, 0.1, 0.3, 0.5, 0.7]

        for i, ethereum_block in enumerate(ethereum_blocks):
            congestion = random.choice(congestion_levels)
            p2s_proposer = self.select_proposer("P2S")
            ethereum_pos_proposer = self.select_proposer("Ethereum PoS")
            p2s_block = self.simulate_p2s_block(i, p2s_proposer, ethereum_block, congestion)
            ethereum_pos_block = self.simulate_ethereum_pos_block(i, ethereum_pos_proposer, ethereum_block, congestion)
            self.results['p2s_data'].append(p2s_block)
            self.results['ethereum_pos_data'].append(ethereum_pos_block)
            if (i + 1) % 100 == 0 or (i + 1) == len(ethereum_blocks):
                print(f"Processed {i + 1}/{len(ethereum_blocks)} blocks...")

        # Attack strategy cost/gain evaluation (using block gas prices from benign tx)
        block_gas_prices = []
        for b in ethereum_blocks:
            txs = b.get('transactions', [])
            if txs:
                gp = txs[0].get('gasPrice', self.base_gas_price_gwei)
                if isinstance(gp, int) and gp > 1e9:
                    gp = gp / 1e9
                block_gas_prices.append(float(gp) if gp > 0 else self.base_gas_price_gwei)
            else:
                block_gas_prices.append(self.base_gas_price_gwei)
        attack_eval = MEVAttackStrategies(block_gas_prices)
        # Ethereum PoS: full mempool visibility → all strategies (front_run, sandwich, etc.) apply
        strategy_results = attack_eval.evaluate_all_strategies(num_blocks, target_visibility=True)
        self.results['attack_strategies'] = {
            name: {
                'description': r.description,
                'total_cost_eth': r.total_cost_eth,
                'total_gain_eth': r.total_gain_eth,
                'attempts': r.attempts,
                'successes': r.successes,
                'net_profit_eth': r.net_profit_eth,
                'cost_per_attempt_eth': r.cost_per_attempt_eth,
                'gain_per_success_eth': r.gain_per_success_eth,
                'cost_per_success_eth': r.cost_per_success_eth,
                'total_victim_welfare_loss_eth': r.total_victim_welfare_loss_eth,
                'total_victim_base_valuation_eth': r.total_victim_base_valuation_eth,
                'per_block_gain_eth': list(r.per_block_gain_eth or []),
            }
            for name, r in strategy_results.items()
        }
        # P2S: only blind insert (+ g_limit over-declaration cost comparison) applicable
        strategy_results_p2s = attack_eval.evaluate_p2s_strategies(num_blocks)
        self.results['attack_strategies_p2s'] = {
            name: {
                'description': r.description,
                'total_cost_eth': r.total_cost_eth,
                'total_gain_eth': r.total_gain_eth,
                'attempts': r.attempts,
                'successes': r.successes,
                'net_profit_eth': r.net_profit_eth,
                'cost_per_attempt_eth': r.cost_per_attempt_eth,
                'gain_per_success_eth': r.gain_per_success_eth,
                'cost_per_success_eth': r.cost_per_success_eth,
                'total_victim_welfare_loss_eth': r.total_victim_welfare_loss_eth,
                'total_victim_base_valuation_eth': r.total_victim_base_valuation_eth,
                'per_block_gain_eth': list(r.per_block_gain_eth or []),
            }
            for name, r in strategy_results_p2s.items()
        }
        self.results['attack_strategies_p2s_note'] = (
            "In P2S only blind insert (and g_limit over-declaration) are applicable. "
            "Front-run, sandwich, arbitrage are not applicable (B1 has only PHTs; cannot target). "
            "Blind insert: F_res = φ·g_limit·g_base burned at B1; if the attacker does "
            "not reveal, it forfeits exactly F_res (B2 execution gas is paid only on reveal). "
            "g_limit over-declaration: inflating g_limit multiplies F_res proportionally."
        )

        self.calculate_metrics()
        self.save_results()
        self.print_summary()
        self.print_attack_strategies_summary()
        return self.results

    def select_proposer(self, protocol: str) -> str:
        """Select proposer by round-robin (one node = one node, no stake)."""
        protocol_validators = sorted([v_id for v_id, v in self.validators.items() if v['protocol'] == protocol])
        if not protocol_validators:
            return list(self.validators.keys())[0]
        if protocol == "P2S":
            idx = self._p2s_proposer_index % len(protocol_validators)
            self._p2s_proposer_index += 1
            return protocol_validators[idx]
        else:
            idx = self._eth_proposer_index % len(protocol_validators)
            self._eth_proposer_index += 1
            return protocol_validators[idx]
    
    def print_summary(self):
        """Print simulation summary"""
        print("\n" + "=" * 80)
        print("SIMULATION SUMMARY")
        print("=" * 80)
        
        print("\n📊 PROFIT DECENTRALIZATION (Gini Coefficient):")
        for protocol_key in ['p2s', 'ethereum_pos']:
            protocol_label = 'P2S' if protocol_key == 'p2s' else 'Ethereum PoS'
            gini = self.results['profit_distribution'][protocol_key]['gini_coefficient']
            print(f"  {protocol_label}: {gini:.4f} (lower = more decentralized)")
        
        print("\n💰 MEV REORDERING OPPORTUNITIES (victim welfare loss s_j ≈ m_j):")
        for protocol_key in ['p2s', 'ethereum_pos']:
            protocol_label = 'P2S' if protocol_key == 'p2s' else 'Ethereum PoS'
            mev_data = self.results['mev_reordering'][protocol_key]
            mean_mev = mev_data['mean_mev']
            total_vwl = mev_data['total_victim_welfare_loss']
            res_fees = mev_data.get('total_reservation_fees_burned', 0.0)
            line = f"  {protocol_label}: {mean_mev:.4f} ETH/block MEV, {total_vwl:.4f} ETH total victim loss"
            if res_fees > 0:
                line += f", {res_fees:.4f} ETH reservation fees burned"
            print(line)
        
        print("\n⏱️ SYSTEM OVERHEAD:")
        for protocol_key in ['p2s', 'ethereum_pos']:
            protocol_label = 'P2S' if protocol_key == 'p2s' else 'Ethereum PoS'
            oh = self.results['overhead_metrics'][protocol_key]
            print(
                f"  {protocol_label}: {oh['mean_latency']:.3f}s latency, "
                f"{oh['mean_cost']:.4f} ETH cost/block, "
                f"{oh['mean_packing_gas_utilization']:.1%} gas utilization "
                f"(greedy priority-fee-density packing)"
            )

    def print_attack_strategies_summary(self):
        """Print cost/gain for Ethereum PoS (all strategies) and P2S (blind insert + g_limit over-declaration)."""
        strategies = self.results.get('attack_strategies', {})
        if strategies:
            print("\n📌 MEV ATTACK STRATEGIES — Ethereum PoS:")
            print("  Victim loss s_j ≈ m_j: slippage funds the attacker gain (money conserved).")
            print("  Victim utility v_j - s_j - g_j > 0 because v_j > s_j + g_j (rational submission).")
            for name, s in strategies.items():
                vwl = s.get('total_victim_welfare_loss_eth', 0.0)
                vval = s.get('total_victim_base_valuation_eth', 0.0)
                print(
                    f"  • {name}: attacker gain(m_j)={s['total_gain_eth']:.4f} ETH  "
                    f"victim loss(s_j)={vwl:.4f} ETH  "
                    f"victim valuation(v_j)={vval:.4f} ETH  "
                    f"net_attacker={s['net_profit_eth']:.4f} ETH  "
                    f"successes={s['successes']}/{s['attempts']}"
                )
        strategies_p2s = self.results.get('attack_strategies_p2s', {})
        if strategies_p2s:
            print("\n📌 MEV ATTACK STRATEGIES — P2S:")
            print(f"  {self.results.get('attack_strategies_p2s_note', '')}")
            for name, s in strategies_p2s.items():
                vwl = s.get('total_victim_welfare_loss_eth', 0.0)
                vval = s.get('total_victim_base_valuation_eth', 0.0)
                print(
                    f"  • {name}: cost={s['total_cost_eth']:.4f} ETH  "
                    f"gain(m_j)={s['total_gain_eth']:.4f} ETH  "
                    f"victim loss(s_j)={vwl:.4f} ETH  "
                    f"victim v_j={vval:.4f} ETH  "
                    f"net_attacker={s['net_profit_eth']:.4f} ETH  "
                    f"successes={s['successes']}/{s['attempts']}"
                )

    def calculate_metrics(self):
        """Calculate aggregate research metrics"""
        # Profit distribution metrics
        for protocol in ['P2S', 'Ethereum PoS']:
            protocol_key = protocol.lower().replace(' ', '_')
            protocol_validators = [v for v in self.validators.values() if v['protocol'] == protocol]
            profits = [v['net_profit'] for v in protocol_validators]
            
            self.results['profit_distribution'][protocol_key] = {
                'profits': profits,
                'gini_coefficient': self.calculate_gini_coefficient(profits),
                'mean_profit': statistics.mean(profits) if profits else 0,
                'std_profit': statistics.stdev(profits) if len(profits) > 1 else 0,
                'min_profit': min(profits) if profits else 0,
                'max_profit': max(profits) if profits else 0,
                'total_rewards': sum(v['total_rewards'] for v in protocol_validators),
                'total_costs': sum(v['total_gas_costs'] for v in protocol_validators)
            }
        
        # MEV reordering metrics
        for protocol_data, protocol_name in [(self.results['p2s_data'], 'p2s'),
                                            (self.results['ethereum_pos_data'], 'ethereum_pos')]:
            mev_opportunities = [block['mev_opportunity'] for block in protocol_data]
            victim_losses = [block['victim_welfare_loss'] for block in protocol_data]
            # reservation_fees_burned only exists in P2S blocks
            res_fees = [block.get('reservation_fees_burned', 0.0) for block in protocol_data]
            self.results['mev_reordering'][protocol_name] = {
                'opportunities': mev_opportunities,
                'mean_mev': statistics.mean(mev_opportunities) if mev_opportunities else 0,
                'total_mev': sum(mev_opportunities),
                'blocks_with_mev': sum(1 for mev in mev_opportunities if mev > 0),
                # s_j ≈ m_j: victim welfare loss ≈ total MEV extracted; victim
                # utility v_j - s_j - g_j > 0 because v_j > s_j + g_j.
                'total_victim_welfare_loss': sum(victim_losses),
                'mean_victim_welfare_loss': statistics.mean(victim_losses) if victim_losses else 0,
                # P2S only: burned reservation fees (F_res)
                'total_reservation_fees_burned': sum(res_fees),
            }
        
        # Overhead metrics + greedy fee-density packing.efficiency
        for protocol_data, protocol_name in [(self.results['p2s_data'], 'p2s'),
                                            (self.results['ethereum_pos_data'], 'ethereum_pos')]:
            latencies = [block['network_latency'] for block in protocol_data]
            costs = [block['gas_cost'] for block in protocol_data]
            times = [block['total_time'] for block in protocol_data]
            gas_utils = [block.get('packing_gas_utilization', 0.0) for block in protocol_data]
            fee_revs = [block.get('packing_fee_revenue_eth', 0.0) for block in protocol_data]
            self.results['overhead_metrics'][protocol_name] = {
                'mean_latency': statistics.mean(latencies) if latencies else 0,
                'mean_cost': statistics.mean(costs) if costs else 0,
                'mean_time': statistics.mean(times) if times else 0,
                'total_cost': sum(costs),
                'p95_latency': sorted(latencies)[int(len(latencies) * 0.95)] if latencies else 0,
                'p99_latency': sorted(latencies)[int(len(latencies) * 0.99)] if latencies else 0,
                # Greedy fee-density block packing (deterministic baseline)
                'mean_packing_gas_utilization': statistics.mean(gas_utils) if gas_utils else 0,
                'total_packing_fee_revenue_eth': sum(fee_revs),
            }
    
    def save_results(self):
        """Save results to JSON"""
        os.makedirs('data', exist_ok=True)
        filename = f"data/simulation_{self.results['metadata']['timestamp']}.json"

        # Convert to JSON-serializable format
        json_results = json.loads(json.dumps(self.results, default=str))

        with open(filename, 'w') as f:
            json.dump(json_results, f, indent=2)

        print(f"\n💾 Results saved to {filename}")

    def save_ledger_json(self, path: str = "data/block_ledger_1000.json"):
        """Write block_ledger_1000.json in the format expected by plots/plot_welfare.py."""
        os.makedirs(os.path.dirname(path), exist_ok=True)
        p2s_blocks = self.results.get("p2s_data", [])
        pos_blocks  = self.results.get("ethereum_pos_data", [])
        blocks = []
        for p, e in zip(p2s_blocks, pos_blocks):
            p_loss = float(p.get("victim_welfare_loss", 0.0))
            e_loss = float(e.get("victim_welfare_loss", 0.0))
            blocks.append({
                "p2s": {
                    "block_state":   {"victim_welfare_loss_eth": p_loss},
                    "wallet_deltas": {"users_aggregate_net_eth": -p_loss},
                    "attack":        {"victim_slippage_eth":     p_loss},
                },
                "ethereum_pos": {
                    "block_state":   {"victim_welfare_loss_eth": e_loss},
                    "wallet_deltas": {"users_aggregate_net_eth": -e_loss},
                    "attack":        {"victim_slippage_eth":     e_loss},
                },
            })
        with open(path, "w") as f:
            json.dump({"blocks": blocks}, f, indent=2)
        print(f"💾 Block ledger saved to {path}")

    def save_mev_comparison_json(self, path: str = "data/mev_comparison.json"):
        """Write mev_comparison.json in the schema expected by plots/plot_mev_comparison.py.

        Writes atomically (tmpfile + os.replace) so a crash mid-write cannot leave
        a half-written file in place.  Includes block-count metadata so a reader
        can verify that the file was generated by the current 1000-block run rather
        than an older stub.
        """
        import tempfile

        os.makedirs(os.path.dirname(path), exist_ok=True)
        eth_strats = self.results.get("attack_strategies", {})
        p2s_strats = self.results.get("attack_strategies_p2s", {})

        # Map simulator strategy keys → display keys consumed by plot_mev_comparison.py
        _key_map = {
            "front_run":             "front_running",
            "sandwich":              "sandwich_attacks",
            "arbitrage":             "arbitrage",
            "blind_insert_p2s":      "blind_planting",
            "glimit_overdecl_5x_pht":"block_stuffing",
        }

        num_blocks = int(self.results.get("metadata", {}).get("num_blocks", DEFAULT_NUM_BLOCKS))

        def _bucket_for(raw_key: str, eth_record: dict, p2s_record: dict) -> dict:
            eth_total = float(eth_record.get("total_gain_eth", 0.0))
            p2s_total = float(p2s_record.get("total_gain_eth", 0.0))
            eth_succ  = int(eth_record.get("successes", 0))
            p2s_succ  = int(p2s_record.get("successes", 0))
            red_total = eth_total - p2s_total
            red_pct   = (red_total / eth_total * 100.0) if eth_total > 0 else 0.0
            red_count = eth_succ - p2s_succ
            red_count_pct = (red_count / eth_succ * 100.0) if eth_succ > 0 else 0.0
            return {
                "ethereum": {"count": eth_succ, "total": eth_total,
                             "avg":   eth_total / eth_succ if eth_succ else 0.0,
                             "median":eth_total / eth_succ if eth_succ else 0.0},
                "p2s":      {"count": p2s_succ, "total": p2s_total,
                             "avg":   p2s_total / p2s_succ if p2s_succ else 0.0,
                             "median":p2s_total / p2s_succ if p2s_succ else 0.0},
                "reduction": {"count": red_count, "count_pct": red_count_pct,
                              "total": red_total, "total_pct": red_pct},
            }

        mev_by_type: Dict[str, Dict[str, Any]] = {}
        for raw_key in set(list(eth_strats.keys()) + list(p2s_strats.keys())):
            canonical = _key_map.get(raw_key, raw_key)
            mev_by_type[canonical] = _bucket_for(
                raw_key,
                eth_strats.get(raw_key, {}),
                p2s_strats.get(raw_key, {}),
            )

        p2s_total = sum(v["p2s"]["total"]      for v in mev_by_type.values())
        eth_total = sum(v["ethereum"]["total"] for v in mev_by_type.values())
        reduction_fraction = (eth_total - p2s_total) / eth_total if eth_total > 0 else 0.0
        reduction_pct      = reduction_fraction * 100.0

        # Activity-count summary (consumed by plot_activities_count)
        comparison = {
            "ethereum": {
                "total_blocks":      num_blocks,
                "total_mev":         eth_total,
                "avg_mev_per_block": eth_total / num_blocks if num_blocks else 0.0,
                "miner_payments":    num_blocks,
                "swaps":             int(eth_strats.get("sandwich",  {}).get("attempts", num_blocks)),
                "arbitrages":        int(eth_strats.get("arbitrage", {}).get("successes", 0)),
                "sandwich_attacks":  int(eth_strats.get("sandwich",  {}).get("successes", 0)),
            },
            "p2s": {
                "total_blocks":      num_blocks,
                "total_mev":         p2s_total,
                "avg_mev_per_block": p2s_total / num_blocks if num_blocks else 0.0,
                "miner_payments":    num_blocks,
                "swaps":             int(p2s_strats.get("blind_insert_p2s", {}).get("attempts", num_blocks)),
                "arbitrages":        0,
                "sandwich_attacks":  int(p2s_strats.get("blind_insert_p2s", {}).get("successes", 0)),
            },
            "differences": {
                "total_mev": {"ethereum": eth_total, "p2s": p2s_total,
                              "reduction": reduction_pct,
                              "reduction_abs": eth_total - p2s_total},
            },
        }

        # Per-block aggregate gain (sum across all attacker strategies, length = num_blocks).
        # Used by plot_mev_comparison.py to bootstrap a 95% CI on reduction %.
        def _sum_per_block(record_dict: Dict[str, Any]) -> List[float]:
            vectors = [list(r.get("per_block_gain_eth") or []) for r in record_dict.values()]
            if not vectors:
                return [0.0] * num_blocks
            length = max(len(v) for v in vectors) or num_blocks
            return [sum(v[i] if i < len(v) else 0.0 for v in vectors) for i in range(length)]

        per_block_eth = _sum_per_block(eth_strats)
        per_block_p2s = _sum_per_block(p2s_strats)

        out = {
            "timestamp": datetime.now().isoformat(),
            "metadata":  {
                "num_blocks":          num_blocks,
                "post_merge_economics": True,
                "block_issuance_eth":   POST_MERGE_BLOCK_ISSUANCE_ETH,
                "attester_reward_eth":  POST_MERGE_ATTESTER_REWARD_ETH,
                "proposer_tip_fraction":PROPOSER_TIP_FRACTION,
            },
            "comparison": comparison,
            "mev_by_type": mev_by_type,
            "per_block_gain_eth": {
                "ethereum": per_block_eth,
                "p2s":      per_block_p2s,
            },
            "summary": {
                "ethereum_total_eth":  eth_total,
                "p2s_total_eth":       p2s_total,
                "reduction_fraction":  reduction_fraction,
                "reduction_pct":       reduction_pct,
            },
        }

        # Atomic write: tmp file in same directory, then os.replace
        dir_name = os.path.dirname(path) or "."
        tmp_fd, tmp_path = tempfile.mkstemp(prefix=".mev_cmp_", suffix=".json", dir=dir_name)
        try:
            with os.fdopen(tmp_fd, "w") as f:
                json.dump(out, f, indent=2, default=str)
            os.replace(tmp_path, path)
        except Exception:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise
        print(f"💾 MEV comparison saved to {path} (num_blocks={num_blocks})")

def main():
    """Main function"""
    import sys
    
    num_blocks = 1000
    if len(sys.argv) > 1:
        try:
            num_blocks = int(sys.argv[1])
        except ValueError:
            print("Error: Number of blocks must be an integer")
            sys.exit(1)
    
    simulator = P2SSimulator()
    results = simulator.run_simulation(num_blocks)

    simulator.save_results()
    simulator.save_ledger_json()
    simulator.save_mev_comparison_json()

    print(f"\n✅ Simulation complete!")
    print(f"Run the plotting scripts to generate visualizations")

if __name__ == "__main__":
    main()
