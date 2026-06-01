"""Exact Uniswap V2 integer math, shared by the workload builder and the MEV
measurement so both agree bit-for-bit with the on-chain MiniAMM contract."""


def amt_out(ain, rin, rout):
    """Uniswap V2 getAmountOut with the 0.3% fee (integer floor division)."""
    aif = ain * 997
    return (aif * rout) // (rin * 1000 + aif)


def sandwich_profit(Re, Rt, F, V):
    """Attacker ETH profit (pre-gas) from front-running victim swap V with a
    front-run F, then selling back, on a pool with reserves (Re ETH, Rt token).
    Returns (profit_wei, attacker_tokens)."""
    tok = amt_out(F, Re, Rt)
    Re1, Rt1 = Re + F, Rt - tok
    tok_v = amt_out(V, Re1, Rt1)
    Re2, Rt2 = Re1 + V, Rt1 - tok_v
    back = amt_out(tok, Rt2, Re2)
    return back - F, tok


def optimal_front(Re, Rt, V, cap, slippage_bps=100):
    """Profit-maximizing front-run F (wei), bounded by the victim's slippage
    tolerance. A real victim sets minAmountOut = (1 - slippage) * quotedOut; the
    attacker can only push price until the victim would receive exactly that,
    beyond which the victim's swap reverts and yields no MEV. So the optimal
    sandwich front-run is the slippage-binding F (sandwich profit increases in F
    up to that bound). Returns (F_wei, profit_wei); (0, 0) if unprofitable.

    slippage_bps: victim slippage tolerance in basis points (default 100 = 1%).
    """
    quoted = amt_out(V, Re, Rt)
    min_out = quoted * (10000 - slippage_bps) // 10000
    # largest F that still lets the victim receive >= min_out
    lo, hi = 0, min(cap, Re)
    while hi - lo > 10**12:  # ~1e-6 ETH resolution
        m = (lo + hi) // 2
        tok = amt_out(m, Re, Rt)
        if Rt - tok <= 0:
            hi = m
            continue
        v_out = amt_out(V, Re + m, Rt - tok)
        if v_out >= min_out:
            lo = m
        else:
            hi = m
    F = lo
    p, _ = sandwich_profit(Re, Rt, F, V)
    if p <= 0 or F == 0:
        return 0, 0
    return F, p
