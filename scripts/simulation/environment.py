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
    RANDOM_SEED,
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
        if trade <= 0 or self.r <= 0:
            return 0.0
        return min((math.sqrt(self.r + trade) - math.sqrt(self.r)) ** 2, MEV_CAP)

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


def load_gas_prices(n: int) -> List[float]:
    """
    Load per-block base fees from the Ethereum block cache (gwei).
    Falls back to uniform random if the cache is absent.
    """
    random.seed(RANDOM_SEED)
    if not os.path.exists(CACHE_PATH):
        return [random.uniform(15, 60) for _ in range(n)]
    with open(CACHE_PATH, encoding="utf-8") as fh:
        cache = json.load(fh)
    prices = []
    for b in list(cache.values())[:n]:
        txs = b.get("transactions", [])
        gp  = txs[0].get("gasPrice", 20e9) if txs else 20e9
        gp  = float(gp) / 1e9 if gp > 1e9 else float(gp)
        prices.append(max(gp, 1.0))
    while len(prices) < n:
        prices.append(random.uniform(15, 60))
    return prices[:n]
