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
    # We do NOT simulate actual AMM swaps; instead we model this as an
    # analytical equality.  Calibrated from: Torres et al. arXiv:2512.17602.
    VICTIM_SLIPPAGE_ALPHA = 1.0   # sandwich / front-run: s_j = m_j

    # ── MEV gain distributions ───────────────────────────────────────────────
    # Log-normal calibrated to empirical MEV data (Torres et al. 2024,
    # arXiv:2512.17602): sandwich median profit $16.35 ≈ 0.0082 ETH at $2000/ETH.
    # Log-normal is the empirically correct shape: heavy tail, many small attacks.
    # Gains are capped at 2.0 ETH to avoid extreme-outlier bias in averages.
    #
    # Shared opportunity: when an attack succeeds in EITHER protocol, it extracts
    # from the same underlying DEX opportunity.  P2S differs in attack PROBABILITY,
    # not in gain SIZE given success.  A single distribution is used for all
    # targeted strategies; blind insert uses a narrower distribution because the
    # attacker cannot pick the best opportunity.
    #
    #   Torres IQR in ETH: $7.47–$43.05 at ~$2000/ETH = 0.0037–0.0215 ETH
    #   → ln(0.0037)=-5.60, ln(0.0215)=-3.84 → sigma ≈ 0.88; we use 1.5 for
    #   a heavier tail (occasional large sandwiches on high-value swaps).
    #
    #   Gas-price note: Torres data spans high-fee periods (~100 gwei); our
    #   block cache reflects lower-fee mainnet (~20 gwei).  At 20 gwei the
    #   sandwich gas cost is ~0.009 ETH, so profitable attacks require
    #   E[gain] > 0.009/0.35 ≈ 0.026 ETH.  We set the median to 0.015 ETH
    #   (≈$30 at $2000/ETH — plausible for mid-to-large DeFi swaps) with
    #   sigma=1.5 → E[gain] = 0.015×exp(1.125) ≈ 0.046 ETH, which is above
    #   the break-even threshold and consistent with profitable sandwich bots.
    MEV_GAIN_MU    = math.log(0.015)  # median gain per successful targeted attack (ETH)
    MEV_GAIN_SIGMA = 1.5              # log-normal tail (Torres IQR-calibrated, adjusted)
    MEV_GAIN_MAX   = 2.0              # hard cap: prevents extreme-outlier bias

    # Blind-insert has narrower distribution (can't select the best opportunity).
    BLIND_GAIN_MU    = math.log(0.004)   # median blind gain ≈ $8 at $2000/ETH
    BLIND_GAIN_SIGMA = 0.8

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
    PHT_RESERVATION_PHI = 0.10  # 10 % of the equivalent full-execution gas cost

    # ── B2 proposer ordering attack ─────────────────────────────────────────
    # INFEASIBLE: P2S protocol structurally prevents B2 from reordering committed
    # transactions.  MT censorship by the step-2 committee is the only residual
    # risk, and is blocked by the f < n/3 BFT assumption (no honest-minority
    # quorum can collude).  Constants retained for reference only.
    B2_ATTACK_PHTS_PER_BLOCK = 5
    B2_PROPOSER_MATCH_PROB   = 0.20

    def __init__(self, block_gas_prices_gwei: List[float]):
        self.block_gas_prices = block_gas_prices_gwei

    @staticmethod
    def gas_cost_eth(gas_price_gwei: float, gas_units: int) -> float:
        """Ethereum mainnet gas cost in ETH: (gas_price_wei * gas_used) / 1e18."""
        return (gas_price_gwei * GWEI_PER_ETH * gas_units) / WEI_PER_ETH

    def _sample_mev_gain(self) -> float:
        """Sample a MEV gain from the calibrated log-normal distribution (targeted attacks)."""
        return min(random.lognormvariate(self.MEV_GAIN_MU, self.MEV_GAIN_SIGMA), self.MEV_GAIN_MAX)

    def _sample_blind_gain(self) -> float:
        """Sample a MEV gain for a blind insert (no target selection → narrower distribution)."""
        return min(random.lognormvariate(self.BLIND_GAIN_MU, self.BLIND_GAIN_SIGMA), self.MEV_GAIN_MAX)

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

        Cost breakdown (B1 step):
          - Normal gas for PHT inclusion (always paid)
          - Reservation fee F_res = φ · g_limit · g_base (burned, always paid)
        Both are charged at B1 regardless of whether the MT is revealed in B2.
        If the attacker does not reveal: only these B1 costs apply.
        If they reveal and succeed: gain is realised in B2.
        """
        gas_price = self.block_gas_prices[block_idx % len(self.block_gas_prices)]
        execution_cost = self.gas_cost_eth(gas_price, self.GAS_BLIND_INSERT)
        # F_res = φ · g_limit · g_base (burned at B1)
        f_res = self.PHT_RESERVATION_PHI * execution_cost
        cost = execution_cost + f_res  # total B1 cost always paid
        # After B1 commits, attacker learns enough to decide whether to reveal.
        # P2S_ATTACK_FITS_RATE: fraction of blocks where the blind PHT happens to
        # match a profitable opportunity once B1 is confirmed.
        attack_fits = random.random() < self.P2S_ATTACK_FITS_RATE
        if not attack_fits:
            return (cost, 0.0, False)  # no reveal → tx dropped, B1 costs already burned
        success = random.random() < self.P2S_ATTACK_SUCCESS_RATE
        gain = (self._sample_blind_gain() if success else 0.0)
        return (cost, gain, success)

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
        """
        gas_price = self.block_gas_prices[block_idx % len(self.block_gas_prices)]
        inflated_gas = int(self.GAS_BLIND_INSERT * inflation_factor)
        execution_cost = self.gas_cost_eth(gas_price, inflated_gas)
        f_res = self.PHT_RESERVATION_PHI * execution_cost  # φ · g_limit · g_base
        cost = execution_cost + f_res
        # No gain: attacker does not extract value, only consumes block space
        return (cost, 0.0, False)

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
        Gain: same log-normal as sandwich — same underlying DEX opportunity.
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
        Gain: log-normal with median 0.0082 ETH ($16.35 at $2000/ETH).
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
        Gain: same log-normal as targeted attacks — arbitrage opportunity sizes
        are comparable to sandwich profits for the same pool pairs.
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
            for i in range(num_blocks):
                cost, gain, success = run_fn(i)
                total_cost += cost
                total_gain += gain
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
        for i in range(num_blocks):
            cost, gain, success = self.run_blind_insert_p2s_no_reveal(i)
            total_cost += cost
            total_gain += gain
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
        Greedy Fee-Density (Greedy-FD) block packing algorithm.

        Matches the algorithm used by Ethereum go-ethereum (Geth) and Flashbots
        rbuilder in production.  Complexity: O(n log n).

        Reference: Heimbach et al. "A First Look at Ethereum Blob Revolution",
        arXiv:2411.03892 (2024) — used as oracle benchmark for real-world
        packing efficiency measurement.  Also: Azouvi & Hicks "Blockchains, MEV
        and the Knapsack Problem", arXiv:2403.19077 (2024).

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

    def simulate_network_delay(self, congestion_level=0.0):
        """Simulate network delay"""
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
        
        # Convert Ethereum transactions then apply Greedy-FD block packing (B1 step).
        # In P2S, B1 packs PHTs by reserved gas capacity (g^limit).  The same
        # Greedy-FD algorithm used by Geth/Flashbots is applied so the comparison
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

        # Block reward: fixed issuance + fraction of tx fees (benign, mainnet-like).
        # Reservation fees are burned, so they are NOT added to proposer reward.
        block_reward = 2.0 + sum(
            self.gas_cost_eth(tx.get('gas_price', self.base_gas_price_gwei), tx.get('gas_limit', 21000)) * 0.1
            for tx in transactions
        )

        # MEV reordering opportunity (reduced in P2S due to hidden details)
        mev_opportunity = self.calculate_reordering_opportunity(transactions) * 0.1

        # Victim welfare loss per block: s_j ≈ m_j (money conserved; slippage funds
        # the attacker gain).  Victim utility v_j - s_j - g_j > 0 because v_j > s_j + g_j.
        # In P2S mev_opportunity is already scaled by 0.1, so welfare loss is naturally low.
        victim_welfare_loss = mev_opportunity * 0.5  # 50 % exploitation rate, s_j ≈ m_j

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
            # Greedy-FD packing metrics (same algorithm as Geth/Flashbots)
            'packing_gas_utilization': b1_pack['gas_utilization'],
            'packing_fee_revenue_eth': b1_pack['total_fee_eth'],
            'packing_excluded_txs': b1_pack['excluded_count'],
        }
    
    def simulate_ethereum_pos_block(self, block_num: int, proposer_id: str, ethereum_block: Dict, congestion: float):
        """Simulate standard Ethereum PoS block using real Ethereum data"""
        start_time = time.time()

        # Convert Ethereum transactions then apply Greedy-FD packing.
        # This is the identical algorithm used by Geth and Flashbots rbuilder in
        # production (Heimbach et al. arXiv:2411.03892, 2024).  Using the same
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
        block_reward = 2.0 + sum(
            self.gas_cost_eth(tx.get('gas_price', self.base_gas_price_gwei), tx.get('gas_limit', 21000)) * 0.1
            for tx in transactions
        )

        # MEV reordering (full visibility in PoS)
        mev_opportunity = self.calculate_reordering_opportunity(transactions) * 1.0

        # Victim welfare loss per block: s_j ≈ m_j (money conserved in AMM sandwich).
        # Victims still execute — utility v_j - s_j - g_j > 0 because v_j > s_j + g_j.
        # Full mempool visibility in PoS means higher exploitation rate (~70 %).
        victim_welfare_loss = mev_opportunity * 0.7  # 70 % exploitation rate, s_j ≈ m_j

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
            # Greedy-FD packing metrics (same algorithm as Geth/Flashbots)
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
                gp = txs[0].get('gasPrice', self.base_gas_price_gwei * GWEI_PER_ETH)
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
            }
            for name, r in strategy_results_p2s.items()
        }
        self.results['attack_strategies_p2s_note'] = (
            "In P2S only blind insert (and g_limit over-declaration) are applicable. "
            "Front-run, sandwich, arbitrage are not applicable (B1 has only PHTs; cannot target). "
            "Blind insert: execution gas + F_res = φ·g_limit·g_base burned at B1; "
            "if attacker does not reveal, only B1 costs apply. "
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
                f"(Greedy-FD packing, ref: Heimbach et al. arXiv:2411.03892)"
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
        
        # Overhead metrics + Greedy-FD packing efficiency
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
                # Greedy-FD block packing (Geth/Flashbots production algorithm)
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
    
    print(f"\n✅ Simulation complete!")
    print(f"Run the plotting scripts to generate visualizations")

if __name__ == "__main__":
    main()
