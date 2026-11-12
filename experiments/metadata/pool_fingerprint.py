#!/usr/bin/env python3
# formerly E1 (scripts/experiments); run from the repo root.
"""E1: what a metadata-only attacker actually earns. Real labels from Swap logs in the
paper's 1,004-block window. Time-ordered: last 30% of blocks are attacked, history is
only earlier blocks. For each block the attacker ranks PHTs by P(swap | public fields),
guesses (pool, direction), and brackets the k best with two plants. Profit for V2 WETH
pools is computed with exact V2 math on the real pre-trade reserves (Sync logs), with a
front leg sized BLIND of the victim (the best fixed size per pool, chosen in hindsight,
which favours the attacker) and a 1% victim slippage bound."""
import json, os, sys, math, collections as C
sys.path.insert(0,'real/scripts'); sys.path.insert(0,'experiments/common')
from v2math import amt_out, sandwich_profit
WETH='c02aaa39b223fe8d0a0e5c4f27ead9083c756cc2'
V2S='0xd78ad95fa46c994b6551d0da85fc275fe613ce37657fb8d5e3d130840159d822'
V3S='0xc42079f94a6350d7e6235f29174924f928cc2ac818eb64fed8004e115fbcca67'
SYNC='0x1c411e9a96e071241c2f21f7726b17ae89e3cab4c78be50e062b03a9fffbbad1'
d=json.load(open('experiments/metadata/cache/swap_logs.json')); logs=sorted(d['logs'],key=lambda l:(l['b'],l['i'])); t0=d['token0']; t1=json.load(open('experiments/metadata/data/token1.json'))
print('logs',len(logs),C.Counter(l['t'][:8] for l in logs))
def w(h,i): return int(h[2+64*i:2+64*(i+1)],16)
res={}; swaps=C.defaultdict(list)    # tx -> [(pool,dir,version,amountin,reserves)]
for l in logs:
    a=l['a']
    if l['t']==SYNC: res[a]=(w(l['d'],0),w(l['d'],1))
    elif l['t']==V2S:
        a0i,a1i=w(l['d'],0),w(l['d'],1); dr=0 if a0i>0 else 1
        swaps[l['tx'].lower()].append((a,dr,2,a0i or a1i,res.get(a)))
    else:
        x=w(l['d'],0); dr=0 if x<2**255 else 1
        swaps[l['tx'].lower()].append((a,dr,3,0,None))
c=json.load(open('data/ethereum_blocks_cache.json')); ks=sorted([k for k in c if k.isdigit()],key=int)
print('tx with swap in sample',len(swaps))
cut=int(ks[int(len(ks)*.7)])
def glb(g): return int(round(math.log2(max(g,1))*4))
def nb(n): return 0 if n==0 else 1+min(int(math.log2(n+1)),12)
# training counts for P(swap|fields)
cnt=[C.defaultdict(C.Counter) for _ in range(4)]; n=C.Counter(); hist=C.defaultdict(lambda:[0,0]); last={}; pop=C.Counter()
def feat(t,bf):
    s=t['from'].lower();h=hist[s]; cls='f' if h[0]==0 else('n' if h[1]==0 else('a' if h[0]==h[1] else 'm'))
    return (glb(t['gas']),nb(int(t['nonce'])),int(math.log2(max(int(t['gasPrice'])-bf,0)/1e9+1)*2),cls)
def post(x):
    o=math.log((n[1]+1)/(n[0]+1))
    for i,v in enumerate(x): o+=math.log((cnt[i][1][v]+.5)/(n[1]+5))-math.log((cnt[i][0][v]+.5)/(n[0]+5))
    return 1/(1+math.exp(-o))
recs=C.defaultdict(list); dbg=C.defaultdict(list); out=C.defaultdict(lambda:[0,0,0.0]); tp=0;all_=0;base=[0,0]
bestF={}
# hindsight-best fixed WETH front size per pool, over train+test (favours the attacker)
GR=[10**e for e in (16,17,18,19)]+[3*10**e for e in (16,17,18)]
def gain(s,F):
    """Exact V2 sandwich profit, only where it is computable: a V2 pool that really holds
    WETH, with the victim buying with WETH. None means not evaluable."""
    a,dr,ver,ain,R=s
    if ver!=2 or R is None: return None
    w0=t0.get(a)==WETH; w1=t1.get(a)==WETH
    if not (w0 or w1): return None
    Re,Rt=(R[0],R[1]) if w0 else (R[1],R[0])
    if (dr==0)!=w0: return None
    V=ain
    if F>Re//3: return 0
    q=amt_out(V,Re,Rt); mn=q*99//100
    tok=amt_out(F,Re,Rt); Re1,Rt1=Re+F,Rt-tok
    if amt_out(V,Re1,Rt1)<mn: return 0        # victim's slippage bound trips, no sandwich
    p,_=sandwich_profit(Re,Rt,F,V); return max(p,0)
pair=set()
for l in logs:pass
for b in (int(k) for k in ks):
    B=c[str(b)]; bf=B['base_fee']; T=B['transactions']; rows=[]
    for t in T:
        x=feat(t,bf); hs=t['hash'].lower(); S=swaps.get(hs,[]); y=int(bool(S)); rows.append((t,x,y,S))
    if b>=cut:
        top=[g for g,_ in pop.most_common(30)]; tot=sum(pop.values()) or 1
        cand=[]
        for t,x,y,S in rows:
            p=post(x); s=t['from'].lower(); gs=[(g,pop[g]/tot) for g in top[:8]]
            if s in last: gs.append((last[s],.5))
            g,w_=max(gs,key=lambda z:z[1]) if gs else (None,0)
            cand.append((p*w_,p,g,t,y,S))
        cand.sort(key=lambda z:-z[0])
        for k in (1,3,10):
            for sc,p,g,t,y,S in cand[:k]:
                hit=any((s[0],s[1])==g for s in S); e=out[k]; e[0]+=1; e[1]+=hit; tp+=0
                if hit: dbg[k].append({'b':b,'tx':t['hash'],'from':t['from'].lower(),'g':g,'ver':[s[2] for s in S if (s[0],s[1])==g][0]})
                v=None
                if hit:
                    q=[[gain(s,F) for s in S if (s[0],s[1])==g] for F in GR]
                    q=[max(z for z in Q if z is not None) for Q in q if any(z is not None for z in Q)]
                    v=(max(q)/1e18) if q else None      # best blind size per hit: generous to the attacker
                recs[k].append((b,int(hit),v))
    for t,x,y,S in rows:
        n[y]+=1
        for i,v in enumerate(x): cnt[i][y][v]+=1
        s=t['from'].lower();hist[s][0]+=1;hist[s][1]+=y
        for q in S: pop[(q[0],q[1])]+=1; last[s]=(q[0],q[1])
import random
rng=random.Random(11); R={}
blocks=sorted({r[0] for r in recs[1]})
LEG=110_000; 
def net(rows,bf_exec,bf_res):
    h=sum(r[1] for r in rows); ev=[r[2] for r in rows if r[2] is not None]
    if not rows or not ev: return None
    hr=h/len(rows); gain_=sum(ev)/len(ev)
    F=.2*200000*bf_res*1e-9; Fb=LEG*bf_exec*1e-9
    return hr*(gain_-2*max(F,Fb))-(1-hr)*2*F, hr, gain_
for k,L in sorted(recs.items()):
    by=C.defaultdict(list)
    for r in L: by[r[0]].append(r)
    ctx={'45.1gwei':(45.1,45.1),'floor_2gwei':(.12,2.),'no_floor_0.12gwei':(.12,.12)}
    o={'brackets':len(L),'hits':sum(r[1] for r in L),'evaluated_hits':sum(r[2] is not None for r in L),'share_evaluated_with_gain':sum(1 for r in L if r[2])/max(1,sum(r[2] is not None for r in L))}
    for nm,(e,f) in ctx.items():
        pt=net(L,e,f); bs=[]
        for _ in range(2000):
            rr=[r for b in rng.choices(blocks,k=len(blocks)) for r in by[b]]; x=net(rr,e,f)
            if x: bs.append(x[0])
        bs.sort(); o[nm]={'net_per_bracket':pt[0],'ci95':[bs[int(.025*len(bs))],bs[int(.975*len(bs))]],'hit_rate':pt[1],'gain_per_hit':pt[2],'net_per_block':pt[0]*k}
    R[k]=o; print(k,json.dumps(o)[:640])
pc=C.Counter(); [pc.update({(s[0],s[1]):1 for s in v}) for v in swaps.values()]
tot=sum(pc.values()); R['top1_pool_dir_share']=pc.most_common(1)[0][1]/tot; R['distinct_pool_dir']=len(pc); R['blocks_attacked']=len(blocks)
json.dump({str(k):v for k,v in R.items()},open('experiments/metadata/data/pool_fingerprint.json','w'),indent=1)
