"""
Rational MEV agent classes for P2S agent-based simulation.

Each agent encodes a distinct attack strategy.  Before acting each block,
an agent checks E[net profit] > 0 at the current φ and gas price; if not,
it abstains (rational exit).  This models profit-driven, adaptive behaviour.

Agent taxonomy:
  SandwichBot      — info-blocked by P2S; structurally inactive at all φ
  FrontrunBot      — info-blocked by P2S; structurally inactive at all φ
  BlindPlanterBot  — info-blocked (speculative PHTs not profitable at ≥58 gwei)
  BlockStufferBot  — deactivates at any φ > 0 (F_res scales with declared gas)
  B2ProposerBot    — primary residual; deactivates at φ ≥ φ* ≈ 0.052
  CrossBlockArbBot — info-blocked; not profitable at empirical gas prices
"""

import random
from abc import ABC, abstractmethod
from typing import List, Tuple

from .constants import (
    MEV_MU, MEV_SIG, MEV_CAP,
    BLIND_MU, BLIND_SIG,
    E_MEV_GAIN, E_BLIND_GAIN,
    GAS_PHT, GAS_PHT_LARGE, GAS_ARB,
    STUFF_GAS_DECLARED, STUFF_N_PHTS, STUFF_E_BENEFIT,
    N_VALIDATORS, B2_MATCH_PROB, B2_N_PHTS,
    ARB_OPP_P2S, ARB_EXEC, ARB_EFF,
    BLIND_FIT, BLIND_SUCCESS,
)
from .environment import AMMPool, Tx, gas_eth


class MevAgent(ABC):
    """
    Base class for rational MEV agents.

    Each block, step() is called:
      1. Evaluate E[net profit] via e_net().
      2. If profitable: call act(), record (cost, gain).
      3. Accumulate stats for activity_rate and mean_net.
    """

    def __init__(self):
        self.reset()

    def reset(self):
        self._active = 0
        self._total  = 0
        self._costs: List[float] = []
        self._gains: List[float] = []

    @property
    def name(self) -> str:
        return type(self).__name__

    @abstractmethod
    def e_net(self, phi: float, pool: AMMPool, gp: float) -> float:
        """Expected net profit per attempt at current conditions (ETH)."""

    @abstractmethod
    def act(self, phi: float, pool: AMMPool, txpool: List[Tx], gp: float) -> Tuple[float, float]:
        """Execute the strategy. Returns (cost_eth, gain_eth)."""

    def step(self, phi: float, pool: AMMPool, txpool: List[Tx], gp: float):
        self._total += 1
        if self.e_net(phi, pool, gp) > 0:
            self._active += 1
            cost, gain = self.act(phi, pool, txpool, gp)
            self._costs.append(cost)
            self._gains.append(gain)

    @property
    def activity_rate(self) -> float:
        return self._active / self._total if self._total else 0.0

    @property
    def mean_net(self) -> float:
        if not self._costs:
            return 0.0
        return (sum(self._gains) - sum(self._costs)) / self._total


# ─────────────────────────────────────────────────────────────────────────────
# Info-blocked agents (structurally inactive under P2S)
# ─────────────────────────────────────────────────────────────────────────────

class SandwichBot(MevAgent):
    """
    Targets DEX swaps via priority-gas-auction sandwich.
    Requires observing victim recipient, value, and calldata before B1 ordering.
    P2S hides these fields until B2 → target identification is impossible.
    """

    def e_net(self, phi, pool, gp) -> float:
        return -1.0  # structurally infeasible

    def act(self, phi, pool, txpool, gp):
        return 0.0, 0.0


class FrontrunBot(MevAgent):
    """
    Inserts a competing transaction ahead of a detected high-value pending tx.
    Requires observing calldata (swap parameters) before ordering — hidden by P2S.
    """

    def e_net(self, phi, pool, gp) -> float:
        return -1.0  # structurally infeasible

    def act(self, phi, pool, txpool, gp):
        return 0.0, 0.0


class BlindPlanterBot(MevAgent):
    """
    Plants PHTs speculatively without knowledge of other transactions.
    Pays F_res = φ · g^limit · g^base at B1 regardless of outcome.

    E[net] = P_fit · P_success · E[blind_gain] − exec_pht · (1 + φ)

    At ≥ 58 gwei: exec_pht ≈ 0.0088 ETH >> E[blind_gain] ≈ 0.000275 ETH.
    Info asymmetry alone makes blind planting irrational at empirical gas prices.
    """

    def e_net(self, phi, pool, gp) -> float:
        e_gain = BLIND_FIT * BLIND_SUCCESS * E_BLIND_GAIN
        cost   = gas_eth(gp, GAS_PHT_LARGE) * (1.0 + phi)
        return e_gain - cost

    def act(self, phi, pool, txpool, gp) -> Tuple[float, float]:
        f_res = gas_eth(gp, GAS_PHT_LARGE) * phi
        exec_ = gas_eth(gp, GAS_PHT_LARGE)
        if random.random() < BLIND_FIT and random.random() < BLIND_SUCCESS:
            dex = [t for t in txpool if t.is_dex]
            gain = (pool.sandwich_profit(max(dex, key=lambda t: t.trade_eth).trade_eth)
                    if dex else
                    min(random.lognormvariate(BLIND_MU, BLIND_SIG), MEV_CAP))
            return f_res + exec_, gain
        return f_res, 0.0


class CrossBlockArbBot(MevAgent):
    """
    Cross-block CFMM arbitrage: commits PHT in B1, reads on-chain state after B2,
    decides whether to reveal in B2.  Does NOT need transaction content.

    At empirical gas (58 gwei), E[net] < 0 regardless of φ.
    """

    def e_net(self, phi, pool, gp) -> float:
        e_gain = ARB_OPP_P2S * ARB_EXEC * ARB_EFF * E_MEV_GAIN
        cost   = gas_eth(gp, GAS_ARB) * (1.0 + phi)
        return e_gain - cost

    def act(self, phi, pool, txpool, gp) -> Tuple[float, float]:
        if random.random() >= ARB_OPP_P2S:
            return 0.0, 0.0
        cost = gas_eth(gp, GAS_ARB) * (1.0 + phi)
        dex  = [t for t in txpool if t.is_dex]
        if not dex:
            return cost, 0.0
        max_gain = pool.sandwich_profit(max(dex, key=lambda t: t.trade_eth).trade_eth) * ARB_EFF
        if ARB_EXEC * max_gain <= cost:
            return 0.0, 0.0
        return (cost, max_gain) if random.random() < ARB_EXEC else (cost, 0.0)


# ─────────────────────────────────────────────────────────────────────────────
# Fee-sensitive agents (deactivate at finite φ)
# ─────────────────────────────────────────────────────────────────────────────

class BlockStufferBot(MevAgent):
    """
    Inflates declared g^limit in PHTs to monopolise B1 block capacity.
    F_res scales linearly with declared gas → attack is self-defeating at any φ > 0.

    E[net] = STUFF_E_BENEFIT − N_phts · φ · gas_eth(gp, g^declared)
    φ*_stuffer ≈ 0.000329 at 58 gwei (deactivates essentially at φ → 0⁺).
    """

    def e_net(self, phi, pool, gp) -> float:
        f_res_total = STUFF_N_PHTS * phi * gas_eth(gp, STUFF_GAS_DECLARED)
        return STUFF_E_BENEFIT - f_res_total

    def act(self, phi, pool, txpool, gp) -> Tuple[float, float]:
        cost = STUFF_N_PHTS * phi * gas_eth(gp, STUFF_GAS_DECLARED)
        gain = E_MEV_GAIN * 0.005 if random.random() < 0.10 else 0.0
        return cost, gain


class B2ProposerBot(MevAgent):
    """
    Colluding B2 proposer attempting transaction reordering in the reveal phase.

    INFEASIBLE under P2S protocol: the mechanism structurally prevents B2 from
    reordering committed transactions. The only residual risk — MT censorship by
    the step-2 committee — is blocked by the f < n/3 BFT assumption, so no
    honest-minority quorum can collude to censor.

    e_net always returns -1.0; act() is never called.
    """

    def e_net(self, phi, pool, gp) -> float:
        return -1.0  # structurally infeasible under f < n/3

    def act(self, phi, pool, txpool, gp) -> Tuple[float, float]:
        return 0.0, 0.0


# Ordered list used by sweep.py
ALL_AGENTS = [
    SandwichBot,
    FrontrunBot,
    BlindPlanterBot,
    BlockStufferBot,
    B2ProposerBot,
    CrossBlockArbBot,
]
