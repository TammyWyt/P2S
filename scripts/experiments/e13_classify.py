#!/usr/bin/env python3
"""E13 part 1: how well can an attacker classify PHTs from public fields alone (Reviewer A)?

Attacker = proposer at S1. It sees, for every PHT in the block: sender, nonce, gas limit,
maxFee, maxPriorityFee, tx type; the block's base fee; and all chain history before the block
(past reveals are public). It never sees to / value / calldata / logs of the current block.

Tasks (labels come from hidden fields, see e13_labels.py):
  T1  protocol class (9 classes) and the binary "is a DEX swap"
  T2  for swaps: (pool, direction) of the first swap leg (strict) or any leg (lenient)
  T3  for correctly guessed swaps: trade size, predicted from public history

Features are prequential: state is updated only after a block closes, so a block's features use
only earlier blocks. Split per window by block order: train 60% / validation 20% / test 20%.
Models are tuned and calibrated on validation and scored once on test. CIs: block bootstrap.

Usage: e13_classify.py WINDOW [--hist-blocks H] [--tag TAG]"""
import argparse, bisect, collections as C, glob, json, math, os, sys
import numpy as np
import lightgbm as lgb
from sklearn.isotonic import IsotonicRegression
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from e13_labels import protocol, CLASSES, CID, TOPICS

ROOT = '/Users/tammy/Code/P2S/data/experiments'
WIN = {'2023': (18748996, 18750000), '2026': (25245959, 25246958)}
NC = len(CLASSES)
SW = CID['dex_swap']
RECENT = 300          # blocks in the "recently popular (pool, dir)" table
RNG = np.random.default_rng(13)


TIER = None          # set by --tier R: every declared gas limit is rounded UP to 21000 * R^k


def tier(g):
    if not TIER:
        return g
    k = math.ceil(math.log(max(g, 21000) / 21000, TIER) - 1e-9)
    return int(round(21000 * TIER ** k))


def gb(g):            # quarter-octave gas-limit bucket
    return int(round(math.log2(max(g, 1)) * 4))


# ----------------------------------------------------------------------------- data
def load(win, hist_blocks):
    a, b = WIN[win]
    hist = []
    for p in sorted(glob.glob(f'{ROOT}/_e13/hist/*.json'), key=lambda x: int(os.path.basename(x)[:-5])):
        c = int(os.path.basename(p)[:-5])
        if a - 21600 <= c < a:
            for n, ts, txs in json.load(open(p)):
                if n >= a - hist_blocks:
                    hist.append((n, [dict(s=t[0], to=t[1], sel=t[2], gas=tier(t[4]), gu=t[5], L=t[7],
                                          cls=protocol(t[1], t[2], t[7], set(t[8]))) for t in txs]))
    blocks = []
    for n in range(a, b + 1):
        d = json.load(open(f'{ROOT}/_e13/blocks/{n}.json'))
        for t in d['txs']:
            t['gas_orig'] = t['gas']
            t['gas'] = tier(t['gas'])
            t['cls'] = protocol(t['to'], t['sel'], t['L'], {x[1] for x in t['logs'] if x[1] in TOPICS})
        blocks.append(d)
    return hist, blocks


# ----------------------------------------------------------------------------- state
class State:
    def __init__(s):
        s.cnt = C.Counter()                                  # sender -> txs
        s.cls = C.defaultdict(lambda: np.zeros(NC))          # sender -> class counts
        s.last_cls = {}
        s.last_blk = {}
        s.util = C.defaultdict(lambda: [0.0, 0])             # sender -> sum(gu/gas), n
        s.pd = C.defaultdict(C.Counter)                      # sender -> (pool,dir) counts
        s.pd_last = C.defaultdict(dict)                      # sender -> (pool,dir) -> last block
        s.pd_amt = C.defaultdict(lambda: C.defaultdict(list))  # sender -> pd -> recent amounts
        s.last_pd = {}
        s.g_cls = C.defaultdict(lambda: np.zeros(NC))        # exact gas limit -> class counts
        s.gb_cls = C.defaultdict(lambda: np.zeros(NC))       # gas bucket -> class counts
        s.g_pd = C.defaultdict(C.Counter)                    # exact gas -> (pool,dir)
        s.gb_pd = C.defaultdict(C.Counter)
        s.pool_amt = C.defaultdict(list)                     # pd -> recent amounts (all senders)
        s.ver = {}                                           # pool -> 2/3/4
        s.recent = C.deque()                                 # per-block lists of pd
        s.rec = C.Counter()

    def update(s, n, txs):
        blk_pd = []
        for t in txs:
            k = CID[t['cls']]
            a = t['s']
            s.cnt[a] += 1
            s.cls[a][k] += 1
            s.last_cls[a] = k
            s.last_blk[a] = n
            u = s.util[a]
            u[0] += t['gu'] / max(t['gas'], 1)
            u[1] += 1
            s.g_cls[t['gas']][k] += 1
            s.gb_cls[gb(t['gas'])][k] += 1
            for i, l in enumerate(t['L']):
                pd = (l[0], l[1])
                s.ver[l[0]] = l[2]
                s.pd[a][pd] += 1
                s.pd_last[a][pd] = n
                am = s.pd_amt[a][pd]
                am.append(l[3])
                del am[:-5]
                pa = s.pool_amt[pd]
                pa.append(l[3])
                del pa[:-50]
                if i == 0:
                    s.last_pd[a] = pd
                    s.g_pd[t['gas']][pd] += 1
                    s.gb_pd[gb(t['gas'])][pd] += 1
                    blk_pd.append(pd)
        s.recent.append(blk_pd)
        s.rec.update(blk_pd)
        if len(s.recent) > RECENT:
            s.rec.subtract(s.recent.popleft())


# ----------------------------------------------------------------------------- T1 features
G1 = ['gas', 'loggas', 'gas_mod1000', 'gas_round10k', 'g_n', 'gb_n'] + \
     [f'g_p{c}' for c in range(NC)] + [f'gb_p{c}' for c in range(NC)]
G2 = ['maxfee_rel', 'tip_gwei', 'type', 'lognonce', 'nonce0']
G3 = ['s_n', 's_since', 's_util', 's_last'] + [f's_p{c}' for c in range(NC)] + ['s_npd', 's_topshare']
G4 = ['b_same_sender', 'b_same_gas', 'b_txs']
GROUPS = {'G1_gas': G1, 'G2_+fees_nonce': G1 + G2, 'G3_+sender_history': G1 + G2 + G3,
          'G4_+block_context': G1 + G2 + G3 + G4}


def t1_feats(st, n, bf, txs):
    ss = C.Counter(t['s'] for t in txs)
    sg = C.Counter(t['gas'] for t in txs)
    out = []
    for t in txs:
        a, g = t['s'], t['gas']
        gc, bc = st.g_cls.get(g), st.gb_cls.get(gb(g))
        gn = gc.sum() if gc is not None else 0
        bn = bc.sum() if bc is not None else 0
        gp = (gc + 0.1) / (gn + 0.1 * NC) if gn else np.full(NC, np.nan)
        bp = (bc + 0.1) / (bn + 0.1 * NC) if bn else np.full(NC, np.nan)
        sn = st.cnt.get(a, 0)
        sc = st.cls[a] if sn else None
        sp = (sc + 0.1) / (sn + 0.1 * NC) if sn else np.full(NC, np.nan)
        u = st.util.get(a)
        pdc = st.pd.get(a)
        f = dict(gas=g, loggas=math.log2(max(g, 1)), gas_mod1000=g % 1000, gas_round10k=int(g % 10000 == 0),
                 g_n=gn, gb_n=bn, maxfee_rel=t['maxfee'] / max(bf, 1), tip_gwei=t['tip'] / 1e9, type=t['ty'],
                 lognonce=math.log2(t['nonce'] + 1), nonce0=int(t['nonce'] == 0),
                 s_n=sn, s_since=(n - st.last_blk[a]) if sn else np.nan, s_util=(u[0] / u[1]) if u else np.nan,
                 s_last=st.last_cls.get(a, -1), s_npd=len(pdc) if pdc else 0,
                 s_topshare=(pdc.most_common(1)[0][1] / sum(pdc.values())) if pdc else np.nan,
                 b_same_sender=ss[a], b_same_gas=sg[g], b_txs=len(txs))
        for c in range(NC):
            f[f'g_p{c}'] = gp[c]
            f[f'gb_p{c}'] = bp[c]
            f[f's_p{c}'] = sp[c]
        out.append(f)
    return out


# ----------------------------------------------------------------------------- T2 candidates
CF = ['c_s_cnt', 'c_s_share', 'c_s_since', 'c_s_islast', 'c_g_cnt', 'c_g_share', 'c_gb_cnt', 'c_gb_share',
      'c_rec_cnt', 'c_rec_rank', 'c_ver', 'src_s', 'src_g', 'src_gb', 'src_rec', 'loggas', 'tip_gwei', 's_n',
      'lognonce']


def candidates(st, t, rec_top):
    a, g = t['s'], t['gas']
    spd = st.pd.get(a, C.Counter())
    c = {}
    for pd, _ in spd.most_common(5):
        c.setdefault(pd, set()).add('s')
    if a in st.last_pd:
        c.setdefault(st.last_pd[a], set()).add('s')
    for pd, _ in st.g_pd.get(g, C.Counter()).most_common(3):
        c.setdefault(pd, set()).add('g')
    for pd, _ in st.gb_pd.get(gb(g), C.Counter()).most_common(3):
        c.setdefault(pd, set()).add('gb')
    for pd in rec_top[:5]:
        c.setdefault(pd, set()).add('rec')
    sn = sum(spd.values())
    gpd = st.g_pd.get(g, C.Counter())
    gn = sum(gpd.values())
    bpd = st.gb_pd.get(gb(g), C.Counter())
    bn = sum(bpd.values())
    rank = {pd: i for i, pd in enumerate(rec_top)}
    rows = []
    for pd, src in c.items():
        rows.append((pd, dict(
            c_s_cnt=spd[pd], c_s_share=spd[pd] / sn if sn else 0,
            c_s_since=(st.pd_last[a][pd] if pd in st.pd_last.get(a, {}) else np.nan),
            c_s_islast=int(st.last_pd.get(a) == pd), c_g_cnt=gpd[pd], c_g_share=gpd[pd] / gn if gn else 0,
            c_gb_cnt=bpd[pd], c_gb_share=bpd[pd] / bn if bn else 0, c_rec_cnt=st.rec[pd],
            c_rec_rank=rank.get(pd, 999), c_ver=st.ver.get(pd[0], 0), src_s=int('s' in src),
            src_g=int('g' in src), src_gb=int('gb' in src), src_rec=int('rec' in src))))
    return rows


def size_pred(st, a, pd):
    am = st.pd_amt.get(a, {}).get(pd)
    if am:
        return float(np.median(am)), 'sender'
    pa = st.pool_amt.get(pd)
    if pa:
        return float(np.median(pa)), 'pool'
    return None, None


# ----------------------------------------------------------------------------- build
def build(win, hist_blocks):
    hist, blocks = load(win, hist_blocks)
    st = State()
    for n, txs in hist:
        st.update(n, txs)
    T1, T2 = [], []
    for d in blocks:
        n, txs = d['n'], d['txs']
        rec_top = [pd for pd, c in st.rec.most_common(10) if c > 0]
        for t, f in zip(txs, t1_feats(st, n, d['bf'], txs)):
            fresh = int(st.cnt.get(t['s'], 0) == 0)
            T1.append(dict(n=n, h=t['h'], y=CID[t['cls']], fresh=fresh, f=f))
            if True:  # every PHT gets candidates: the attacker cannot tell swaps apart
                truth_first = (t['L'][0][0], t['L'][0][1]) if t['L'] else None
                truth_any = {(l[0], l[1]) for l in t['L']}
                cs = candidates(st, t, rec_top)
                rows = []
                for pd, cf in cs:
                    cf.update(loggas=f['loggas'], tip_gwei=f['tip_gwei'], s_n=f['s_n'], lognonce=f['lognonce'])
                    cf['c_s_since'] = n - cf['c_s_since'] if cf['c_s_since'] == cf['c_s_since'] else np.nan
                    sp, ssrc = size_pred(st, t['s'], pd)
                    rows.append(dict(pd=pd, f=cf, y=int(pd == truth_first), size=sp, size_src=ssrc))
                true_amt = t['L'][0][3] if t['L'] else None
                T2.append(dict(n=n, h=t['h'], is_swap=int(t['cls'] == 'dex_swap'), has_leg=int(bool(t['L'])),
                               fresh=fresh, first=truth_first, any=truth_any, true_amt=true_amt,
                               ver=t['L'][0][2] if t['L'] else None, cands=rows))
        st.update(n, txs)
    return blocks, T1, T2


# ----------------------------------------------------------------------------- stats
def boot(blocks_of_rows, stat, B=1000):
    """Block-clustered bootstrap. blocks_of_rows: dict block -> list of per-row values."""
    ks = list(blocks_of_rows)
    vals = []
    for _ in range(B):
        pick = RNG.choice(len(ks), len(ks))
        vals.append(stat([v for i in pick for v in blocks_of_rows[ks[i]]]))
    return [float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))]


def by_block(rows, val):
    d = C.defaultdict(list)
    for r in rows:
        d[r['n']].append(val(r))
    return d


def auc(y, s):
    o = np.argsort(s)
    r = np.empty(len(s))
    r[o] = np.arange(1, len(s) + 1)
    pos = y.sum()
    return float((r[y == 1].sum() - pos * (pos + 1) / 2) / (pos * (len(y) - pos)))


def lgb_fit(X, y, Xv, yv, multi):
    p = dict(objective='multiclass' if multi else 'binary', learning_rate=0.05, num_leaves=63,
             min_data_in_leaf=50, feature_fraction=0.8, bagging_fraction=0.8, bagging_freq=1,
             lambda_l2=1.0, verbose=-1, seed=13, num_threads=8)
    if multi:
        p['num_class'] = NC
    m = lgb.train(p, lgb.Dataset(X, y), 2000, valid_sets=[lgb.Dataset(Xv, yv)],
                  callbacks=[lgb.early_stopping(50, verbose=False)])
    return m


# ----------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('win')
    ap.add_argument('--hist-blocks', type=int, default=21600)
    ap.add_argument('--tag', default='')
    ap.add_argument('--tier', type=float, default=0)
    A = ap.parse_args()
    global TIER
    TIER = A.tier or None
    blocks, T1, T2 = build(A.win, A.hist_blocks)
    ns = [d['n'] for d in blocks]
    c1, c2 = ns[int(len(ns) * .6)], ns[int(len(ns) * .8)]
    part = lambda r: 'tr' if r['n'] < c1 else ('va' if r['n'] < c2 else 'te')
    allt = [t for d in blocks for t in d['txs'] if t['st'] == 1]
    util = lambda key: float(sum(t['gu'] for t in allt) / sum(t[key] for t in allt))
    out = dict(window=A.win, hist_blocks=A.hist_blocks, tier=A.tier, blocks=len(ns), txs=len(T1),
               utilization=dict(declared=util('gas_orig'), tiered=util('gas')),
               split=dict(train_end=c1, val_end=c2), t1={}, t2={}, t3={})
    print('built', len(T1), 'txs', flush=True)

    # ---------------- T1: protocol class, per feature group
    S = {k: [r for r in T1 if part(r) == k] for k in ('tr', 'va', 'te')}
    for gname, cols in GROUPS.items():
        X = {k: np.array([[r['f'][c] for c in cols] for r in S[k]], float) for k in S}
        y = {k: np.array([r['y'] for r in S[k]]) for k in S}
        m = lgb_fit(X['tr'], y['tr'], X['va'], y['va'], True)
        P = {k: m.predict(X[k], num_iteration=m.best_iteration) for k in ('va', 'te')}
        pred = P['te'].argmax(1)
        yt = y['te']
        acc = float((pred == yt).mean())
        f1 = []
        for c in range(NC):
            tp = ((pred == c) & (yt == c)).sum()
            fp = ((pred == c) & (yt != c)).sum()
            fn = ((pred != c) & (yt == c)).sum()
            if tp + fn:
                f1.append(2 * tp / max(2 * tp + fp + fn, 1))
        # binary "is swap", calibrated on validation (isotonic)
        iso = IsotonicRegression(out_of_bounds='clip').fit(P['va'][:, SW], (y['va'] == SW).astype(int))
        ps = iso.predict(P['te'][:, SW])
        ysw = (yt == SW).astype(int)
        top1 = np.argsort(-ps)[:max(1, len(ps) // 100)]
        rows = [dict(n=r['n'], ok=int(p == r['y'])) for r, p in zip(S['te'], pred)]
        res = dict(accuracy=acc, accuracy_ci=boot(by_block(rows, lambda r: r['ok']), np.mean),
                   macro_f1=float(np.mean(f1)), swap_auc=auc(ysw, ps), swap_base_rate=float(ysw.mean()),
                   swap_prec_top1pct=float(ysw[top1].mean()),
                   swap_brier=float(np.mean((ps - ysw) ** 2)),
                   majority_baseline=float((yt == np.bincount(y['tr']).argmax()).mean()))
        if gname.startswith('G4'):
            cm = np.zeros((NC, NC), int)
            for a_, b_ in zip(yt, pred):
                cm[a_, b_] += 1
            res['confusion'] = cm.tolist()
            res['per_class'] = {CLASSES[c]: dict(n=int((yt == c).sum()),
                                                 recall=float(((pred == c) & (yt == c)).sum() / max((yt == c).sum(), 1)),
                                                 precision=float(((pred == c) & (yt == c)).sum() / max((pred == c).sum(), 1)))
                                for c in range(NC)}
            fr = np.array([r['fresh'] for r in S['te']])
            res['by_sender'] = {k: dict(n=int(msk.sum()), accuracy=float((pred[msk] == yt[msk]).mean()),
                                        swap_auc=auc(ysw[msk], ps[msk]) if 0 < ysw[msk].sum() < msk.sum() else None)
                                for k, msk in (('fresh', fr == 1), ('repeat', fr == 0))}
            imp = m.feature_importance('gain')
            res['top_features'] = sorted(zip(cols, (imp / imp.sum()).round(4).tolist()), key=lambda x: -x[1])[:12]
            pswap_te = {r['h']: float(p) for r, p in zip(S['te'], ps)}
        out['t1'][gname] = res
        print('T1', gname, {k: (round(v, 4) if isinstance(v, float) else '') for k, v in res.items()
                            if isinstance(v, float)}, flush=True)

    # ---------------- T2: (pool, direction) given swap; train/eval on txs with a Uniswap leg
    sw = {k: [r for r in T2 if part(r) == k and r['has_leg'] and r['cands']] for k in ('tr', 'va', 'te')}
    allsw = {k: [r for r in T2 if part(r) == k and r['has_leg']] for k in ('tr', 'va', 'te')}

    def mat(rs):
        X, y, g = [], [], []
        for r in rs:
            for c in r['cands']:
                X.append([c['f'][k] for k in CF])
                y.append(c['y'])
            g.append(len(r['cands']))
        return np.array(X, float), np.array(y), g

    Xtr, ytr, _ = mat(sw['tr'])
    Xva, yva, gva = mat(sw['va'])
    Xte, yte, gte = mat(sw['te'])
    m2 = lgb_fit(Xtr, ytr, Xva, yva, False)
    sva = m2.predict(Xva, num_iteration=m2.best_iteration)
    ste = m2.predict(Xte, num_iteration=m2.best_iteration)
    # calibrate P(top candidate correct) on validation
    def tops(rs, s, g):
        i = 0
        o = []
        for r, k in zip(rs, g):
            ss = s[i:i + k]
            order = np.argsort(-ss)
            o.append((r, [r['cands'][j] for j in order], ss[order]))
            i += k
        return o
    Tva, Tte = tops(sw['va'], sva, gva), tops(sw['te'], ste, gte)
    iso2 = IsotonicRegression(out_of_bounds='clip').fit([s[0] for _, _, s in Tva],
                                                        [int(c[0]['pd'] == r['first']) for r, c, _ in Tva])
    nte = len(allsw['te'])
    hit_s = {r['h']: int(c[0]['pd'] == r['first']) for r, c, _ in Tte}
    hit_l = {r['h']: int(c[0]['pd'] in r['any']) for r, c, _ in Tte}
    hit3 = {r['h']: int(any(x['pd'] == r['first'] for x in c[:3])) for r, c, _ in Tte}
    cover = {r['h']: int(any(x['pd'] == r['first'] for x in r['cands'])) for r in sw['te']}
    rows = [dict(n=r['n'], s=hit_s.get(r['h'], 0), l=hit_l.get(r['h'], 0), t3=hit3.get(r['h'], 0),
                 cov=cover.get(r['h'], 0), fresh=r['fresh'], ver=r['ver']) for r in allsw['te']]

    def summ(rs):
        if not rs:
            return None
        return dict(n=len(rs), top1_strict=float(np.mean([r['s'] for r in rs])),
                    top1_strict_ci=boot(by_block(rs, lambda r: r['s']), np.mean, 500),
                    top1_lenient=float(np.mean([r['l'] for r in rs])), top3_strict=float(np.mean([r['t3'] for r in rs])),
                    candidate_coverage=float(np.mean([r['cov'] for r in rs])))
    out['t2'] = dict(all=summ(rows), fresh=summ([r for r in rows if r['fresh']]),
                     repeat=summ([r for r in rows if not r['fresh']]),
                     by_version={str(v): summ([r for r in rows if r['ver'] == v]) for v in (2, 3, 4)},
                     baseline_recent_popular=float(np.mean([int(any(x['pd'] == r['first'] and x['f']['c_rec_rank'] == 0
                                                                    for x in r['cands'])) for r in allsw['te']])))
    imp = m2.feature_importance('gain')
    out['t2']['top_features'] = sorted(zip(CF, (imp / imp.sum()).round(4).tolist()), key=lambda x: -x[1])[:10]
    print('T2', {k: v for k, v in out['t2']['all'].items() if not isinstance(v, list)}, flush=True)

    # ---------------- T3: size, on correctly guessed swaps
    err = []
    src = C.Counter()
    for r, c, _ in Tte:
        if c[0]['pd'] == r['first'] and c[0]['size'] and r['true_amt']:
            err.append(abs(math.log10(c[0]['size'] / r['true_amt'])))
            src[c[0]['size_src']] += 1
    err = np.array(err)
    out['t3'] = dict(n=len(err), median_abs_log10=float(np.median(err)) if len(err) else None,
                     within_2x=float((err <= math.log10(2)).mean()) if len(err) else None,
                     within_10x=float((err <= 1).mean()) if len(err) else None, source=dict(src))
    print('T3', out['t3'], flush=True)

    # ---------------- per-PHT predictions on test blocks, for the Eq. 5 stage
    preds = []
    t2map = {r['h']: (c, s) for r, c, s in Tte}
    for r in T2:
        if part(r) != 'te':
            continue
        cs = t2map.get(r['h'])
        if cs is None and r['cands']:
            # non-swap or no-leg tx: rank its candidates too, the attacker cannot tell
            X = np.array([[c['f'][k] for k in CF] for c in r['cands']], float)
            s = m2.predict(X, num_iteration=m2.best_iteration)
            o = np.argsort(-s)
            cs = ([r['cands'][j] for j in o], s[o])
        top = []
        if cs:
            for c, s in list(zip(cs[0], cs[1]))[:3]:
                top.append(dict(pool=c['pd'][0], dir=c['pd'][1], p_given_swap=float(iso2.predict([s])[0]),
                                size=c['size']))
        preds.append(dict(n=r['n'], h=r['h'], p_swap=pswap_te.get(r['h']), is_swap=r['is_swap'], first=r['first'],
                          any=sorted(r['any']), true_amt=r['true_amt'], top=top))
    tag = A.tag or f'h{A.hist_blocks}'
    json.dump(out, open(f'{ROOT}/e13_classify_{A.win}_{tag}.json', 'w'), indent=1)
    json.dump(preds, open(f'{ROOT}/_e13/preds_{A.win}_{tag}.json', 'w'))
    print('saved', flush=True)


if __name__ == '__main__':
    main()
