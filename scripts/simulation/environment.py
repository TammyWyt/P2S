"""
P2S simulation environment: AMM pool, transaction pool, and gas helpers.

Models a single Ethereum-compatible block slot with:
  - AMMPool: constant-product CFMM (Angeris 2021) with mean-reverting reserves
  - Tx: typed transaction with hidden fields (PHT semantics)
  - build_txpool: generates a realistic pending transaction pool
  - gas_eth: converts gas units + gas price to ETH cost
"""

import json
import math
import os
import random
from dataclasses import dataclass
from typing import List

from .constants import (
    WEI_PER_ETH, GWEI_PER_ETH, MEV_CAP,
    RANDOM_SEED, sample_mev_gain,
)

_DATA_DIR  = os.path.join(os.path.dirname(__file__), "..", "..", "data")
CACHE_PATH = os.path.join(_DATA_DIR, "ethereum_blocks_cache.json")

# Transaction pool priors
_TX_PRIORS = {"eth_transfer": 0.30, "erc20": 0.20, "dex_swap": 0.35, "complex": 0.15}
_GAS_RANGES = {
    "eth_transfer": (21_000,   25_000),
    "erc20":        (45_000,  130_000),
    "dex_swap":     (80_000,  260_000),
    "complex":      (180_000, 600_000),
}
_TRADE_MU, _TRADE_SIG, _TRADE_CAP = math.log(5.5), 1.2, 200.0


class AMMPool:
    """
    Constant-product AMM.
    Exact sandwich profit formula (Angeris 2021):
        profit*(Δ_v) = (√(r + Δ_v) − √r)²
    Reserves mean-revert across blocks (Qin 2021).
    """
    REVERT = 0.30
    NOISE  = 0.04

    def __init__(self, reserve: float = 1_000.0):
        self.r0 = reserve
        self.r  = reserve

    def sandwich_profit(self, trade: float) -> float:
        # Heavy-tailed MEV draw (median anchored to measurement, tail from the
        # literature; see constants.py). The trade/reserve guard is retained so
        # "no opportunity this block" still yields zero.
        if trade <= 0 or self.r <= 0:
            return 0.0
        return sample_mev_gain(random)

    def step(self) -> None:
        shock  = random.gauss(0, self.NOISE) * self.r
        self.r = max(self.r + self.REVERT * (self.r0 - self.r) + shock, 10.0)


@dataclass
class Tx:
    tx_type:   str
    gas_limit: int
    trade_eth: float = 0.0

    @property
    def is_dex(self) -> bool:
        return self.tx_type == "dex_swap"


def build_txpool(n: int) -> List[Tx]:
    """Generate n transactions drawn from realistic type/gas distributions."""
    pool = []
    for _ in range(n):
        tx_type = random.choices(list(_TX_PRIORS), weights=list(_TX_PRIORS.values()))[0]
        lo, hi  = _GAS_RANGES[tx_type]
        trade   = (min(random.lognormvariate(_TRADE_MU, _TRADE_SIG), _TRADE_CAP)
                   if tx_type == "dex_swap" else 0.0)
        pool.append(Tx(tx_type, random.randint(lo, hi), trade))
    return pool


def gas_eth(gp_gwei: float, gas_units: int) -> float:
    """Convert gas units at a given base fee (gwei) to ETH cost."""
    return (gp_gwei * GWEI_PER_ETH * gas_units) / WEI_PER_ETH


# ── EIP-1559 dynamic base fee ────────────────────────────────────────────────
# Mainnet block parameters and the base-fee update rule, used by the sustained
# block-stuffing (DDoS) experiment in stuffing_duration.py.
GAS_LIMIT_BLOCK = 30_000_000     # mainnet block gas limit
GAS_TARGET      = 15_000_000     # EIP-1559 target = half the gas limit
BASE_FEE_FLOOR  = 1.0            # gwei; matches the cache flooring in load_gas_prices
BASE_FEE_DENOM  = 8              # EIP-1559: max ±1/8 = ±12.5% change per block


def next_base_fee(base_fee_gwei: float, gas_used: float,
                  target: float = GAS_TARGET,
                  floor: float = BASE_FEE_FLOOR) -> float:
    """One EIP-1559 base-fee update.

        base_fee_{n+1} = base_fee_n * (1 + (gas_used - target) / target / 8)

    clamped below at `floor`. A full block (gas_used = 2*target) raises the base
    fee by the maximal +12.5%; an empty block (gas_used = 0) lowers it by -12.5%.
    Reference: EIP-1559 (https://eips.ethereum.org/EIPS/eip-1559).
    """
    delta = (gas_used - target) / target / BASE_FEE_DENOM
    return max(base_fee_gwei * (1.0 + delta), floor)


def median_base_fee() -> float:
    """Median historical mainnet base fee (gwei) from the block cache, used as
    the starting point for the sustained-stuffing experiments."""
    from .constants import PRIORITY_FEE_GWEI
    eff  = load_gas_prices(1005)
    base = sorted(max(g - PRIORITY_FEE_GWEI, BASE_FEE_FLOOR) for g in eff)
    return base[len(base) // 2]


def load_gas_prices(n: int) -> List[float]:
    """
    Load per-block effective gas prices (base_fee + PRIORITY_FEE_GWEI) from the
    Ethereum block cache, cycling through the 1005-block history as needed.

    EIP-1559 split:
      base_fee          — burned by the protocol (per block, from cache)
      PRIORITY_FEE_GWEI — paid to the proposer per gas unit (constant tip)
      effective         — what the attacker declares as maxFeePerGas = base + tip

    Falls back to uniform [20, 50] gwei base fee if the cache is absent.
    """
    from .constants import PRIORITY_FEE_GWEI

    if not os.path.exists(CACHE_PATH):
        random.seed(RANDOM_SEED)
        return [random.uniform(20, 50) + PRIORITY_FEE_GWEI for _ in range(n)]

    with open(CACHE_PATH, encoding="utf-8") as fh:
        cache = json.load(fh)

    base_fees: List[float] = []
    for b in cache.values():
        bf = b.get("base_fee", 0)
        bf_gwei = float(bf) / 1e9 if float(bf) > 1e9 else float(bf)
        base_fees.append(max(bf_gwei, 1.0))

    effective = [bf + PRIORITY_FEE_GWEI for bf in base_fees]
    result: List[float] = []
    while len(result) < n:
        result.extend(effective)
    return result[:n]
