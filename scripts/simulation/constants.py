"""Shared simulation constants — calibrated to empirical Ethereum data."""

import math
import numpy as np

WEI_PER_ETH  = 1e18
GWEI_PER_ETH = 1e9

# MEV gain distribution — heavy-tailed log-normal. The MEDIAN is anchored to our
# own on-chain sandwich detection (real/data/sandwiches.json: 55 real Uniswap
# V2/V3 sandwiches, median 0.00056 ETH ~ $1.7). The TAIL (sigma) is set from the
# published MEV literature, not from that small low-fee sample, which under-counts
# whales: real sandwich profit is heavy-tailed, so the mean is tail-driven. With
# sigma = 2.85 the mean is ~0.033 ETH (~$100, in the Qin/Torres range), ~1% of
# sandwiches exceed 0.5 ETH, and rare whale sandwiches reach tens of ETH, bounded
# at a realistic single-event maximum (MEV_CAP = 50 ETH). Blind planters cannot
# pick the best opportunity, so they draw the worse of two such samples.
MEV_MU,   MEV_SIG,   MEV_CAP   = math.log(0.00056), 2.85, 50.0
BLIND_MU, BLIND_SIG             = math.log(0.0003), 2.5
E_MEV_GAIN   = min(math.exp(MEV_MU   + MEV_SIG**2   / 2), MEV_CAP)  # ≈ 0.033 ETH (mean, tail-driven)
E_BLIND_GAIN = min(math.exp(BLIND_MU + BLIND_SIG**2 / 2), MEV_CAP)  # ≈ 0.0068 ETH


def sample_mev_gain(rng):
    """One realized content-dependent MEV gain (ETH): heavy-tailed log-normal,
    median anchored to measurement, tail from the literature, capped at MEV_CAP."""
    return min(rng.lognormvariate(MEV_MU, MEV_SIG), MEV_CAP)

# Gas limits per operation (units)
GAS_FRONTRUN      = 200_000
GAS_PHT           = 150_000   # PHT inclusion + F_res base
GAS_PHT_LARGE     = 200_000   # blind planter PHTs
GAS_ARB           = 300_000
STUFF_GAS_DECLARED = GAS_PHT * 8   # 8× declared limit for block stuffing

# Attack parameters
N_VALIDATORS  = 5
ARB_OPP_P2S   = 0.10   # cross-DEX arb opportunity rate under P2S
ARB_EXEC      = 0.60   # arbitrage execution success rate
ARB_EFF       = 0.80   # price-efficiency capture factor
BLIND_FIT     = 0.10   # fraction of blocks where blind PHT aligns to a target
BLIND_SUCCESS = 0.50   # success rate given alignment
B2_MATCH_PROB = 0.20   # probability a pre-committed PHT matches a victim MT
B2_N_PHTS     = 5      # PHTs pre-committed per proposer slot

# Block stuffer
STUFF_N_PHTS    = 10
STUFF_E_BENEFIT = E_MEV_GAIN   # monopolist captures full uncontested MEV opportunity

# Simulation defaults
RANDOM_SEED = 42
N_BLOCKS    = 3_000

# EIP-1559 priority fee (tip) paid to the block proposer per gas unit (gwei).
# Base fee is burned; proposer receives only the priority fee.
# Calibrated to Ethereum mainnet post-Merge median tip (~1–3 gwei in normal conditions).
PRIORITY_FEE_GWEI = 1.5

# φ sweep: 20 evenly log-spaced points from 10^-4 to 10^0.
# Uniform spacing on the log axis gives a smooth line when plotted on a log scale.
# φ > 1 is economically incoherent (F_res > full execution cost).
# At empirical mainnet gas (~34.5 gwei base + 1.5 gwei tip = 36 gwei):
#   φ*_stuffer ≈ 0.107   (BlockStufferBot deactivates at median 36 gwei; ~0.066–0.154 across 20–58.6 gwei)
#   BlindPlanterBot and CrossBlockArbBot: never profitable at any φ (exec cost >> E[gain])
PHI_SWEEP = [0.0] + list(np.logspace(-4, 0, 20))
