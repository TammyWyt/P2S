#!/usr/bin/env python3
# formerly E2b (scripts/experiments); run from the repo root.
"""E2b: drive Equation 6 with the real per-block utilization sequence and report what
honest users pay, as declared vs under learned limits. Out-of-sample (second half)."""
import json, os, collections as C
import numpy as np
r=json.load(open(os.path.join(os.path.dirname(__file__),'..','..','data','revert_receipts_cache.json')))
ks=sorted([k for k in r if k.isdigit()],key=int); cut=int(len(ks)*.5)
key=lambda t:(t.get('to') or '',t.get('method') or '')
hist=C.defaultdict(list)
for k in ks[:cut]:
    for t in r[k]['transactions']:
        if t['status']=='ok' or t.get('result')=='success': hist[key(t)].append(t['gas_used'])
Q={k:np.quantile(v,.99)*1.1 for k,v in hist.items() if len(v)>=5}
def limits(t,mode):
    g,L=t['gas_used'],t['gas_limit']
    if mode=='declared': return L
    if mode=='wallet_1.25x': return min(L,int(g*1.25))
    if key(t) in Q:
        n=min(L,int(Q[key(t)])); return L if n<g else n
    return L
out={}
for mode in ('declared','learned_p99x1.1','wallet_1.25x'):
    blocks=[[(t['gas_used'],limits(t,mode)) for t in r[k]['transactions']] for k in ks[cut:]]
    for ustar in (.437,.5,.55,.6,.7,.9):   # .9 = the paper's u*
        phi=.2; ph=[]; extra=0.;fee=0.;bind=0;n=0
        for b in blocks:
            ph.append(phi)
            U=sum(g for g,_ in b);D=sum(L for _,L in b)
            for g,L in b:
                n+=1; fee+=g
                if g<phi*L: bind+=1; extra+=phi*L-g
            phi=max(.2,phi*(1+.5*(ustar-U/D)/ustar))
        ph=np.array(ph)
        out[f'{mode}|{ustar}']={'phi_mean':float(ph.mean()),'phi_p99':float(np.quantile(ph,.99)),'phi_max':float(ph.max()),'share_blocks_at_floor':float((ph<=.2001).mean()),'tx_share_paying_extra':bind/n,'gas_surcharge_pct':100*extra/fee}
        print(mode,ustar,{a:round(b,4) for a,b in out[f'{mode}|{ustar}'].items()})
json.dump(out,open('experiments/utilization/data/honest_phi.json','w'),indent=1)
