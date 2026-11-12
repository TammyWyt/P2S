#!/usr/bin/env python3
"""E13 part 2: feed the measured classification back into Equation 5, end to end, on mainnet state.

For every test block n of a window, on an anvil fork of block n-1 (Uniswap V2, V3, V4 all run in
the EVM, with each victim's real calldata, so its real slippage bound applies):

  PoS (content visible).  For every real swap in the block, the attacker knows the victim's
    content and picks the most profitable front size on a log grid. This is what P2S takes away.

  P2S (public fields only, attacker = proposer).  From part 1, each PHT i has a calibrated
    p_i = P(swap) * P(pool, dir | swap) and a predicted trade size from public history. The
    attacker estimates the prize m_i by simulating its bracket against a synthetic victim of the
    predicted size with an assumed slippage tolerance, and picks its front size from that. It
    bets when p_i * m_i > 2 F_res. At reveal time it sees the victim's opening and either opens
    both legs (paying execution gas) or withholds both (losing 2 F_res): the selective reveal.

Results are stored per block; e13_attack_report.py applies the fee rule for any phi.
Usage: e13_attack.py WINDOW TAG [--workers 3]"""
import collections as C, argparse, json, math, os, sys, time, traceback
from multiprocessing import Pool
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from e13_sim import Anvil, V4Keys

ROOT = '/Users/tammy/Code/P2S/data/experiments'
GRID = [0.02, 0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10, 20]   # front size, multiples of the victim's input
SLIPS = (0.005, 0.01, 0.03, 0.10)                    # slippage tolerances the blind attacker may assume
LEG_GAS = 100_000                                    # rough gas per leg, only for the pruning bound
P_MIN = 0.05                                         # PHTs below this p_i are never worth simulating
TOP_K = 15                                           # at most this many candidate PHTs per block


def net_eth(a, r, tin, pool, ver, key, z, bf):
    """Attacker's ETH profit for one sandwich result, minus the gas of its two legs at base fee bf."""
    g = a.to_eth(tin, r['profit_in'], pool, ver, key, z)
    if g is None:
        return None, None
    legs = (r['gas'][0] + r['gas'][-1]) if len(r['gas']) == 3 else 0
    return g, legs


def best_front(a, pool, ver, key, z, victim, base_in, ts, tin, bf, check=None):
    """Log-grid search for the front size with the highest gross-minus-gas profit."""
    best = (0.0, 0, None, 0)            # (net, front, gross, leg_gas)
    prev = None
    for m in GRID:
        f = max(int(base_in * m), 1)
        r = a.sandwich(pool, ver, key, z, f, victim, ts)
        ok = r['status'][1] == 1 and (check is None or check(r))
        g, legs = net_eth(a, r, tin, pool, ver, key, z, bf)
        if g is None:
            return None
        net = g - legs * bf / 1e18
        if ok and net > best[0]:
            best = (net, f, g, legs)
        if not ok:
            break                      # a larger front only tightens the victim's bound further
        if prev is not None and net < prev:
            break
        prev = net
    return best


def label_to_input(a, pool, ver, key, z, amt):
    """Part-1 sizes are |amount0| for V3/V4 and the input amount for V2; convert to input units."""
    if ver == 2 or z:
        return int(amt)
    return a.quote(pool, ver, key, True, int(amt), a.deploy('probe'))     # token0 -> token1


def kind(e):
    m = str(e)
    if '429' in m or 'rate l' in m or 'Max retries' in m or 'timed out' in m:
        return 'rate_limit'
    if 'no slot found' in m:
        return 'no_balance_slot'          # token with non-standard storage: cannot fund the attacker
    if 'reverted' in m:
        return 'token_reverted'           # transfer-restricted / taxed token: attacker legs revert
    return 'error'


def retry(fn, tries=6):
    for t in range(tries):
        try:
            return fn()
        except Exception as e:
            if kind(e) != 'rate_limit' or t == tries - 1:
                raise
            time.sleep(15 * (t + 1))


def run_block(job):
    import multiprocessing as mp
    win, tag, n, _ = job
    port = 8600 + (mp.current_process()._identity[0] if mp.current_process()._identity else 0)
    out_p = f'{ROOT}/_e13/sim/{win}_{tag}/{n}.json'
    if os.path.exists(out_p):
        return n, 'cached'
    K = V4Keys()
    d = json.load(open(f'{ROOT}/_e13/blocks/{n}.json'))
    preds = [p for p in PREDS[n]]
    bf, ts = d['bf'], d['ts']
    txs = {t['h']: t for t in d['txs']}
    a = Anvil(port, n - 1)
    rec = dict(n=n, bf=bf, pos=[], p2s=[], skipped=C.Counter(), skipped_p2s=C.Counter())
    old_p = f'{ROOT}/_e13/sim/{win}_{tag}_v1/{n}.json'
    old = json.load(open(old_p)) if os.path.exists(old_p) else None
    try:
        # deploy every helper before any sandwich: anvil keeps the latest mined timestamp even
        # after evm_revert, so a helper deployed later would need a timestamp below the victim's
        for name in ('attacker', 'victim', 'probe'):
            a.deploy(name)
        # ---------------- PoS: content-visible attacker, every real swap
        def pos_one(t):
            pool, dr, ver, _ = t['L'][0]
            z = dr == 0
            key = K.get(pool) if ver == 4 else None
            if ver == 4 and key is None:
                rec['skipped']['no_key'] += 1
                return
            if True:
                al = a.sandwich(pool, ver, key, z, 0, ('real', t), ts)
                vin = al['victim_in']
                tin, _ = a.io(pool, ver, key, z)
                if not vin or vin <= 0:
                    rec['skipped']['no_victim_swap'] += 1
                    return
                val = a.to_eth(tin, vin, pool, ver, key, z)
                if val is None:
                    rec['skipped']['unconvertible'] += 1
                    return
                if val < 2 * LEG_GAS * bf / 1e18:
                    # the attacker cannot gain more than the victim's whole input: never profitable
                    rec['pos'].append(dict(h=t['h'], ver=ver, net=0.0, front=0, gross=None, leg_gas=0, value=val, pruned=1))
                    return
                b = best_front(a, pool, ver, key, z, ('real', t), vin, ts, tin, bf)
                if b is None:
                    rec['skipped']['unconvertible'] += 1
                    return
                rec['pos'].append(dict(h=t['h'], ver=ver, net=b[0], front=b[1], gross=b[2], leg_gas=b[3], value=val, pruned=0))

        if old is not None:          # PoS side already measured in v1; only the P2S side had the bug
            rec['pos'], rec['skipped'] = old['pos'], C.Counter(old['skipped'])
        for t in ([] if old is not None else d['txs']):
            if not t['L'] or t['st'] != 1:
                continue
            try:
                retry(lambda: pos_one(t))
            except Exception as e:
                rec['skipped'][kind(e)] += 1
                if len(rec.setdefault('err', [])) < 5:
                    rec['err'].append(traceback.format_exc()[-400:])
        # ---------------- P2S: blind bracket from public fields
        cands = []
        for p in preds:
            if p['p_swap'] is None or not p['top']:
                continue
            c = p['top'][0]
            pi = p['p_swap'] * (c['p_given_swap'] or 0)
            if pi >= P_MIN and c['size']:
                cands.append((pi, p, c))
        cands.sort(key=lambda x: -x[0])
        def p2s_one(pi, p, c):
                pool, dr = c['pool'], c['dir']
                z = dr == 0
                ver = 4 if pool.startswith('0x') and len(pool) == 66 else None
                if ver is None:
                    # V2 or V3: tell them apart by the pool's interface
                    try:
                        a.eth_call(pool, '0x0902f1ac')          # getReserves() exists only on V2
                        ver = 2
                    except Exception:
                        ver = 3
                key = K.get(pool) if ver == 4 else None
                if ver == 4 and key is None:
                    return
                tin, tout = a.io(pool, ver, key, z)
                size = label_to_input(a, pool, ver, key, z, c['size'])
                if not size:
                    return
                pval = a.to_eth(tin, size, pool, ver, key, z)
                if pval is None:
                    rec['skipped_p2s']['unconvertible'] += 1
                    return
                row = dict(h=p['h'], ver=ver, p=pi, pred_value=pval,
                           correct=int(p['first'] is not None and p['first'][0] == pool and p['first'][1] == dr),
                           is_swap=p['is_swap'], by_slip={})
                if pval >= 2 * LEG_GAS * bf / 1e18:
                    q = a.quote(pool, ver, key, z, size, a.deploy('probe'))
                    for sl in SLIPS:
                        chk = lambda r, sl=sl: r['victim_out'] is not None and r['victim_out'] >= (1 - sl) * q
                        est = best_front(a, pool, ver, key, z, ('synthetic', size), size, ts, tin, bf, chk)
                        if est is None:
                            break
                        e = dict(m_hat=est[0], front=est[1], leg_gas_est=est[3], realized_gross=None,
                                 realized_leg_gas=None, victim_ok=None)
                        if row['correct'] and est[1] > 0 and p['h'] in txs:
                            r = a.sandwich(pool, ver, key, z, est[1], ('real', txs[p['h']]), ts)
                            g, legs = net_eth(a, r, tin, pool, ver, key, z, bf)
                            e.update(realized_gross=g, realized_leg_gas=legs, victim_ok=int(r['status'][1] == 1))
                        row['by_slip'][str(sl)] = e
                rec['p2s'].append(row)

        for pi, p, c in cands[:TOP_K]:
            try:
                retry(lambda: p2s_one(pi, p, c))
            except Exception as e:
                rec['skipped_p2s'][kind(e)] += 1
                if len(rec.setdefault('err', [])) < 10:
                    rec['err'].append(traceback.format_exc()[-400:])
    finally:
        rec['ts_bumped'] = getattr(a, 'ts_bumped', 0)
        a.close()
    if rec['skipped']['rate_limit'] + rec['skipped_p2s']['rate_limit']:
        return n, 'rate_limited', dict(rec['skipped'])     # not saved: rerun the block later
    os.makedirs(os.path.dirname(out_p), exist_ok=True)
    json.dump(rec, open(out_p + '.tmp', 'w'))
    os.replace(out_p + '.tmp', out_p)
    return n, len(rec['pos']), len(rec['p2s'])


PREDS = {}


def init(win, tag):
    global PREDS
    for p in json.load(open(f'{ROOT}/_e13/preds_{win}_{tag}.json')):
        PREDS.setdefault(p['n'], []).append(p)


def worker(job):
    try:
        return run_block(job)
    except Exception:
        return job[2], 'fail', traceback.format_exc()[-300:]


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('win')
    ap.add_argument('tag')
    ap.add_argument('--workers', type=int, default=3)
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--offset', type=int, default=0)     # start at this index (another runner from the middle)
    ap.add_argument('--reverse', action='store_true')   # a second runner on another RPC can work from the end
    A = ap.parse_args()
    init(A.win, A.tag)
    blocks = sorted(PREDS, reverse=A.reverse)
    blocks = blocks[A.offset:] + blocks[:A.offset]
    if A.limit:
        blocks = blocks[:A.limit]
    jobs = [(A.win, A.tag, n, 8600 + i % A.workers) for i, n in enumerate(blocks)]
    with Pool(A.workers, initializer=init, initargs=(A.win, A.tag)) as P:
        for k, r in enumerate(P.imap_unordered(worker, jobs)):
            print(k, r, flush=True)
    print('done', flush=True)
