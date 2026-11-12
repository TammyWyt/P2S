#!/usr/bin/env python3
# formerly E7 (scripts/experiments); run from the repo root.
"""E7: top-1 pool+direction prediction from fields a PHT shows before S1 (sender, nonce, gas limit,
fees) plus the sender's strictly earlier history. A prediction hits if it equals any (pool,dir) the
tx swapped, which favours the attacker on multi-hop txs. Train/test on the Sec. 6.1 swaps is time
ordered 70/30. Victim test: 45 replayed V2 victims with history strictly before the target block.
 spec    : global tables from the 10,248 swaps, which POSTDATE every victim (mild lookahead)
 strict  : global tables only from sampled-window swaps before the target block"""
import json, glob, math, os, sys, collections as C
sys.path.insert(0,'experiments/common')
import numpy as np
from netgraph import wilson
sys.path.insert(0,'scripts')
from revert_cost_analysis import _is_dex
_c=json.load(open('data/revert_receipts_cache.json'))
DEX={t['hash'] for k,b in _c.items() if k.isdigit() for t in b['transactions'] if _is_dex(t) and t['status']=='ok'}
print('dex ok in cache',len(DEX),flush=True)
Bk={}
for p in glob.glob('experiments/metadata/cache/swap_label_blocks/*.json'):
    d=json.load(open(p)); Bk[d['n']]=d
W6=range(25245959,25246959)
def lab(r): return {(l[0],l[1]) for l in r['L']}
def rows(bs,dex=False):
    for b in sorted(bs):
        for r in Bk[b]['rows']:
            if r['st']==1 and (not dex or r['h'] in DEX): yield b,r
S61=list(rows(W6,True)); lab61=[x for x in S61 if lab(x[1])]
print('sec6.1 swaps',len(DEX),'fetched',len(S61),'with V2/V3/V4 label',len(lab61),flush=True)
gb=lambda g:int(round(math.log2(max(g,1))*4)); nb=lambda n:min(int(math.log2(n+1)),14); fb=lambda t:int(math.log2(t/1e7+1))
class T:
    def __init__(s): s.pop=C.Counter(); s.g=C.defaultdict(C.Counter); s.gb=C.defaultdict(C.Counter); s.n=C.defaultdict(C.Counter); s.f=C.defaultdict(C.Counter); s.tot=0
    def add(s,r):
        for l in lab(r):
            s.pop[l]+=1; s.g[r['gas']][l]+=1; s.gb[gb(r['gas'])][l]+=1; s.n[nb(r['nonce'])][l]+=1; s.f[fb(r['tip'])][l]+=1; s.tot+=1
def mc(c,k): return [l for l,_ in sorted(c.items(),key=lambda x:(-x[1],x[0]))[:k]]   # ties: lowest (pool,dir), not hash order
def top(c): return mc(c,1)[0] if c else None
def sfreq(H): return top(C.Counter(l for ls in H for l in ls))
def base(tb,r,H): return top(tb.pop)
def a_pred(tb,r,H): return sfreq(H) or top(tb.pop)
def b_pred(tb,r,H): return top(tb.g.get(r['gas'],C.Counter())) or top(tb.gb.get(gb(r['gas']),C.Counter())) or top(tb.pop)
def cands(tb,r,H):
    c=C.Counter(l for ls in H for l in ls); o=mc(c,3)
    for t in (tb.g.get(r['gas']),tb.gb.get(gb(r['gas']))):
        if t: o+=mc(t,2)
    o+=mc(tb.pop,2)
    return list(dict.fromkeys(o))
def feat(tb,r,H,l):
    c=C.Counter(x for ls in H for x in ls); n=sum(c.values())
    def pr(t):
        return math.log((t[l]+.1)/(sum(t.values())+1)) if t else -8.
    last=int(bool(H) and l in H[-1])
    return [1,c[l]/n if n else 0,last,math.log1p(n),pr(tb.g.get(r['gas'])),pr(tb.gb.get(gb(r['gas']))),pr(tb.n.get(nb(r['nonce']))),pr(tb.f.get(fb(r['tip']))),math.log((tb.pop[l]+.1)/(tb.tot+1))]
def fit(X,y,it=400):
    X=np.array(X,float); y=np.array(y,float); mu=X.mean(0); sd=X.std(0)+1e-9; sd[0]=1;mu[0]=0; Z=(X-mu)/sd; w=np.zeros(Z.shape[1])
    for _ in range(it):
        p=1/(1+np.exp(-Z@w)); w-=.5*(Z.T@(p-y)/len(y)+1e-3*w)
    return w,mu,sd
def c_pred(m):
    w,mu,sd=m
    def f(tb,r,H):
        cs=cands(tb,r,H)
        if not cs: return None
        return max(cs,key=lambda l:float(((np.array(feat(tb,r,H,l))-mu)/sd)@w))
    return f
# time-ordered 70/30 on the labelled Sec. 6.1 swaps
cut=int(len(lab61)*.7); cut_in=int(cut*.7); tb=T(); hist=C.defaultdict(list); X=[];Y=[]
for i,(b,r) in enumerate(lab61[:cut]):
    if i>=cut_in:
        for l in cands(tb,r,hist[r['s']]): X.append(feat(tb,r,hist[r['s']],l)); Y.append(int(l in lab(r)))
    tb.add(r); hist[r['s']].append(lab(r))
print('classifier rows',len(X),'pos',sum(Y),flush=True)
M=fit(X,Y); P={'baseline_popular':base,'a_sender_history':a_pred,'b_gas_lookup':b_pred,'c_classifier':c_pred(M)}
res={k:0 for k in P}; has=0; n=0
for b,r in lab61[cut:]:
    H=hist[r['s']]; n+=1; has+=bool(H)
    for k,f in P.items(): res[k]+= f(tb,r,H) in lab(r)
    hist[r['s']].append(lab(r))           # history grows; tables stay frozen at train
overall={k:dict(top1=v/n,ci95=wilson(v,n)) for k,v in res.items()}
print(n,overall,flush=True)
# rebuild tables on all 10,248 for the spec test
tbs=T()
for b,r in lab61: tbs.add(r)
win=sorted(b for b in Bk if b not in W6)
wr=[(b,r) for b,r in rows(win) if lab({'L':r['L']})]
V=json.load(open('experiments/metadata/data/victims.json'))
H={}
for p in glob.glob('experiments/metadata/cache/victim_history/h_*.json'):
    _,bl,s=os.path.basename(p)[:-5].split('_'); L=[]
    for x in sorted(json.load(open(p)),key=lambda z:z['b']):
        q=f"experiments/metadata/cache/victim_history/r_{x['h']}.json"
        if x['s']==s and os.path.exists(q):
            ls={(l[0],l[1]) for l in json.load(open(q))}
            if ls: L.append(ls)
    H[(int(bl),s)]=L
fv=[v for v in V if v['tx']]; O={'spec':{},'strict':{}}; D=[]
for v in fv:
    r=v['tx']; h=H.get((v['block'],r['s']),[]); y={(v['label'][0],v['label'][1])}; tr=T()
    for b,x in wr:
        if b<v['block']: tr.add(x)
    row=dict(block=v['block'],sender=r['s'],hist_swaps=len(h),pool_in_hist=any(y&s for s in h))
    for nm,t in (('spec',tbs),('strict',tr)):
        for k,f in P.items():
            hit=f(t,r,h) in y; O[nm][k]=O[nm].get(k,0)+hit; row[f'{nm}_{k}']=bool(hit)
    D.append(row)
nv=len(fv)
vic={nm:{k:dict(hits=c,top1=c/nv,ci95=wilson(c,nv)) for k,c in O[nm].items()} for nm in O}
bk=max(vic['strict'],key=lambda k:vic['strict'][k]['top1']); bs=max(vic['spec'],key=lambda k:vic['spec'][k]['top1'])
best=vic['strict'][bk] if vic['strict'][bk]['top1']>=vic['spec'][bs]['top1'] else vic['spec'][bs]
out=dict(swaps_sec61=len(DEX),labelled=len(lab61),test_n=n,test_sender_has_history=has/n,overall=overall,victims_found=nv,victim_senders=len({d['sender'] for d in D}),victims_with_any_history=sum(d['hist_swaps']>0 for d in D),victims_pool_dir_seen_before=sum(d['pool_in_hist'] for d in D),victims=vic,p_best_victims=best['top1'],p_best_victims_ci95=best['ci95'],rows=D)
json.dump(out,open('experiments/metadata/data/predict_pool_direction.json','w'),indent=1)
print(json.dumps({k:v for k,v in out.items() if k!='rows'},indent=1))
