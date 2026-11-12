#!/usr/bin/env python3
# formerly E11 (scripts/experiments); run from the repo root.
"""E11: P2S vs simplified Shutter and BEAT-MEV models on netsim, N=1000, K=150, 100 runs.
Parameters from each design's publications; simplified models, compute shown separately.
Shutter (Gnosis spec, Shutter forum 'Shutterized Optimism: Performance Evaluation'): keyper set
7 (alpha set), range 5-50; threshold 2/3; 48 B share; keys released once the block is seen; share
gen/verify <2 ms, aggregation <10 ms, decryption <1 ms per tx. Ciphertext overhead is not published:
96 B is our assumption. Live deployment reports keys 'just over one second' after the trigger.
BEAT-MEV (USENIX Sec '25, Sec. 7): ciphertext 722 B + 208 B CCA proof (proof off-chain); partial
decryption 80.1 ms at B=128, 297.0 ms at B=512 (Opt-2); 48 B share (normal), 2*sqrt(B) elements
(Opt-2); Combine 500.8 ms at B=128, 3.8 s at B=512 serial, 439 ms parallel at B=512. No committee
size is stated, so n is swept with threshold 2/3."""
import json, math, sys, os
from multiprocessing import Pool
sys.path.insert(0,os.path.join(os.path.dirname(os.path.abspath(__file__)),'..','common'))
from netgraph import *
N=1000;K=150;RUNS=100;TX=374;PHT=77;MT=371
def lin(x,a,b,c,d): return b+(x-a)*(d-b)/(c-a)
PD=lin(K,128,80.1,512,297.0)/1000
LG=math.log(3800/500.8)/math.log(4); CB=.5008*(K/128)**LG; CBP=CB*.439/3.8
OPT2=2*math.ceil(math.sqrt(K))*48
def gos(n,src,b): r,m,by=n.gossip(src,b); return n.pct(r,.9),by
def many(n,k,b): t,by=gos(n,0,b); return t+ns.serial_s(k*b),k*by
def p2s(n):
    _,m=many(n,K,PHT); t1,b1=gos(n,0,K*PHT); tr,br=many(n,K,MT); t2,b2=gos(n,0,K*MT); return t1+tr+t2,m+b1+br+b2,0.0
def committee(n,enc,block,C,share):
    _,m=many(n,K,enc); t1,b1=gos(n,0,K*block); th=(2*C)//3+1; arr=[];bs=0
    for i in range(C):
        r,_,by=n.gossip((i*7)%n.n,share); arr.append(n.pct(r,.9)); bs+=by
    return t1+sorted(arr)[th-1],m+b1+bs
def shutter(C):
    def f(n):
        t,b=committee(n,TX+96,TX+96,C,48); return t,b,.002+.01+K*.001
    return f
def beat(C,opt):
    def f(n):
        t,b=committee(n,TX+722+208,TX+722,C,OPT2 if opt else 48)
        return t,b,PD+(CBP if opt else 0)
    return f
D={'p2s':p2s,'pos':lambda n:(*[x for x in (lambda r:(r[0],r[1]*2))(gos(n,0,K*TX))],0.0)}
for C in (7,50): D[f'shutter_C{C}']=shutter(C)
for C in (7,50,100): D[f'beat_C{C}_opt2_parallel']=beat(C,True)
def one(a):
    k,s=a; n=ns.Net(N,seed=31337*s+N); return k,D[k](n)
if __name__=='__main__':
    with Pool(9) as p: R=p.map(one,[(k,s) for k in D for s in range(RUNS)])
    o={}
    for k in D:
        X=np.array([r[1] for r in R if r[0]==k]); m=X.mean(0); ci=1.96*X[:,0].std(ddof=1)/RUNS**.5
        o[k]=dict(net_s=m[0],ci95=ci,compute_s=m[2],total_s=m[0]+m[2],mb=m[1]/1e6)
    o['constants']=dict(beat_partial_s=PD,beat_combine_serial_s=CB,beat_combine_parallel_s=CBP,beat_opt2_share_B=OPT2,per_tx_overhead_B=dict(p2s_hash=32,shutter_assumed=96,beat_onchain=722,beat_with_proof=930))
    json.dump(o,open('experiments/comparison/data/three_way.json','w'),indent=1); print(json.dumps(o,indent=1))
