#!/usr/bin/env python3
# formerly E5 (scripts/experiments); run from the repo root.
"""E5: head-to-head on one workload and one network model (netsim.Net, N=1000, K=150, 40 seeds).
Bandwidth counts mempool gossip for every design: netsim's PoS baseline omits it, while
P2S's reveal gossip is charged, which overstates P2S's ratio. Sizes are stated below.
Second part: EIP-8209 vs P2S on real June 2026 blocks, from each spec's own formula."""
import json, os, sys, statistics as st
sys.path.insert(0,os.path.join(os.path.dirname(__file__),'..','..','scripts','simulation'))
import netsim as ns
N=1000;K=150;SEEDS=40
TX=374;PHT=77;MT=371
ENC=TX+96            # threshold ciphertext overhead (KEM header + tag), assumption
SHARE=96             # BLS decryption share, assumption
COMMIT8209=180;REVEAL8209=MT+60  # frame-tx envelopes, assumption
def gos(net,src,b):
    r,m,by=net.gossip(src,b); return net.pct(r,.9),by
def many(net,k,b):
    t,by=gos(net,0,b); return t+ns.serial_s(k*b),k*by      # netsim.reveal_phase semantics
def pos(net):
    _,m=many(net,K,TX); t,b=gos(net,0,K*TX); return t,m+b,{}
def boost(net):                                            # builder->relay->proposer->relay->network
    _,m=many(net,K,TX); rel=[net.one_way_s(0,v) for v in range(1,40)]; hop=st.mean(rel)
    t,b=gos(net,0,K*TX); return t+4*hop+ns.serial_s(K*TX),m+b,{}
def p2s(net,agr=False):
    _,m=many(net,K,PHT); t1,b1=gos(net,0,K*PHT); tr,br=many(net,K,MT); t2,b2=gos(net,0,K*MT)
    ta=ba=0
    if agr: ta,_,ba=ns.agreement_bls(net,K)
    return t1+tr+ta+t2,m+b1+br+ba+b2,{}
def shutter(C):
    def f(net):
        _,m=many(net,K,ENC); t1,b1=gos(net,0,K*ENC)
        th=(2*C)//3+1; arr=[]; bs=0
        for i in range(C):
            r,_,by=net.gossip((i*7)%net.n,SHARE); arr.append(net.pct(r,.9)); bs+=by
        ts=sorted(arr)[th-1]
        return t1+ts,m+b1+bs,{}
    return f
def e8209(net):                                            # per-slot flow at a full commit load
    _,m=many(net,K,COMMIT8209); t,b=gos(net,0,K*COMMIT8209); tr,br=many(net,K,REVEAL8209); t2,b2=gos(net,0,K*MT)
    return t+tr+t2,m+b+br+b2,{}
D={'pos':pos,'mev_boost':boost,'p2s':p2s,'p2s_threshold':lambda n:p2s(n,True),'shutter_C10':shutter(10),'shutter_C100':shutter(100),'eip8209':e8209}
rows={}
for name,f in D.items():
    L=[];B=[]
    for s in range(SEEDS):
        net=ns.Net(N,seed=31337*s+N); t,b,_=f(net); L.append(t);B.append(b)
    rows[name]={'latency_s':st.mean(L),'ci95':1.96*st.stdev(L)/SEEDS**.5,'mb':st.mean(B)/1e6}
    print(name,{k:round(v,3) for k,v in rows[name].items()},flush=True)
for k in rows: rows[k]['mb_vs_pos']=rows[k]['mb']/rows['pos']['mb']; rows[k]['lat_vs_pos']=rows[k]['latency_s']/rows['pos']['latency_s']
# --- real blocks, spec formulas
import numpy as np
r=json.load(open(os.path.join(os.path.dirname(__file__),'..','..','data','revert_receipts_cache.json')))
ks=[k for k in r if k.isdigit()]
COMMIT_RES=1_000_000;PHI=.2;FLOOR=2.0
tx=[];cov=[];cov_gas=[];counts=[]
over=0;pen=[];pen_same=[];cost_extra=[]
for k in ks:
    b=r[k];T=b['transactions'];bf=b['base_fee']/1e9;cap=b['gas_limit']//COMMIT_RES
    counts.append(len(T));ct=0;c=0
    for t in sorted(T,key=lambda x:x['gas_limit']):
        n=max(1,-(-t['gas_limit']//COMMIT_RES))
        if ct+n<=cap: ct+=n;c+=1
        over+=t['gas_limit']>COMMIT_RES
        e=COMMIT_RES*n*bf*1.125
        pen.append(e/max(PHI*t['gas_limit']*max(bf,FLOOR),1e-9)); pen_same.append(e/max(PHI*t['gas_limit']*bf,1e-9))
    if T: cov.append(c/len(T))
sw=[(t,b) for b in (r[k] for k in ks) for t in b['transactions'] if t['to_name'] in('UniversalRouter','UniswapV2Router02','DexRouter')]
gl=np.median([t['gas_limit'] for t,_ in sw]);bf=np.median([b['base_fee'] for b in (r[k] for k in ks)])/1e9
real={'blocks':len(ks),'mean_tx_per_block':float(np.mean(counts)),'cap_per_block':60,'best_case_commit_coverage_mean':float(np.mean(cov)),'tx_over_1M_gas':over/sum(counts),
 'median_swap_gas_limit':float(gl),'median_base_gwei':float(bf),
 'nonreveal_swap_eip8209_eth':COMMIT_RES*bf*1.125e-9,'nonreveal_swap_p2s_floor_eth':PHI*gl*max(bf,FLOOR)*1e-9,'nonreveal_swap_p2s_nofloor_eth':PHI*gl*bf*1e-9,
 'penalty_ratio_median_with_floor':float(np.median(pen)),'penalty_ratio_median_same_base':float(np.median(pen_same))}
print(real)
json.dump({'N':N,'K':K,'seeds':SEEDS,'sizes':{'TX':TX,'PHT':PHT,'MT':MT,'ENC':ENC,'SHARE':SHARE,'COMMIT8209':COMMIT8209,'REVEAL8209':REVEAL8209},'net':rows,'real_blocks':real},open('experiments/comparison/data/head_to_head.json','w'),indent=1)
