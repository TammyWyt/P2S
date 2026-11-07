#!/usr/bin/env python3
"""E2: is honest over-declaration inherent? Replays real June 2026 receipts: each sender
declares a limit learned from earlier gas use of the same (to, method), out-of-sample.
Reports block utilization and out-of-gas rate, then runs the stuffing model at the
achievable target. Reproduces Table 4 first as a check."""
import json, os, sys, collections as C
sys.path.insert(0,os.path.join(os.path.dirname(__file__),'..','..'))
import numpy as np
from scripts.simulation.environment import GAS_LIMIT_BLOCK, gas_eth, next_base_fee, median_base_fee
from scripts.simulation.stuffing_duration import next_reservation_fee, simulate_duration, MAX_CHANGE
from scripts.simulation.constants import PRIORITY_FEE_GWEI
OUT=os.path.join(os.path.dirname(__file__),'..','..','data','experiments')
r=json.load(open(os.path.join(os.path.dirname(__file__),'..','..','data','revert_receipts_cache.json')))
ks=sorted([k for k in r if k.isdigit()],key=int); cut=int(len(ks)*.5)
def key(t): return (t.get('to') or '',t.get('method') or '')
hist=C.defaultdict(list)
for k in ks[:cut]:
    for t in r[k]['transactions']:
        if t['status']=='ok' or t.get('result')=='success': hist[key(t)].append(t['gas_used'])
def quant(q,buf):
    return {k:np.quantile(v,q)*buf for k,v in hist.items() if len(v)>=5}
rows=[]
base=[]
pol={'p95x1.1':(.95,1.1),'p99x1.1':(.99,1.1),'p99x1.25':(.99,1.25),'maxx1.25':(1.0,1.25)}
res={}
blocks=ks[cut:]
orig=[]
for name,(q,b) in pol.items():
    Q=quant(q,b); us=[]; oog=tot=cov=0
    for k in blocks:
        dec=used=0
        for t in r[k]['transactions']:
            tot+=1; g=t['gas_used']; L=t['gas_limit']
            if key(t) in Q:
                cov+=1; nl=min(L,int(Q[key(t)]))
                if nl<g: oog+=1; nl=L   # would have failed: sender retries at original limit
            else: nl=L
            dec+=nl; used+=g
        us.append(used/dec)
    res[name]={'u_mean':float(np.mean(us)),'u_p10':float(np.quantile(us,.1)),'u_min':float(min(us)),'covered':cov/tot,'oog_rate':oog/tot}
us=[sum(t['gas_used'] for t in r[k]['transactions'])/sum(t['gas_limit'] for t in r[k]['transactions']) for k in blocks]
res['as_declared']={'u_mean':float(np.mean(us)),'u_p10':float(np.quantile(us,.1)),'u_min':float(min(us))}
print(json.dumps(res,indent=1))
# Stuffing worst case, same loop as stuffing_duration.simulate_adaptive, with u* free
def adaptive(budget,r_,ustar,bf0,phi=.2,s=MAX_CHANGE):
    bf=bf_res=bf0; n=0; tg=1-ustar
    while n<2000000:
        c=phi*gas_eth(bf_res,GAS_LIMIT_BLOCK)+gas_eth(bf+PRIORITY_FEE_GWEI,int(r_*GAS_LIMIT_BLOCK))
        if c>budget: break
        budget-=c;n+=1
        bf=next_base_fee(bf,r_*GAS_LIMIT_BLOCK)
        bf_res=next_reservation_fee(bf_res,1-r_,u_target=tg)
    return n
bf0=median_base_fee()
def worst(u):
    return max(adaptive(1000.,i/100,u,bf0) for i in range(101))
tab={u:worst(u) for u in (.9,.85,.8,.75,.7,.65,.6,.55,.5,.437)}
print('check Table 4 (60,1032,23654):',tab[.9],tab[.5],tab[.437]); print(tab,'eth',simulate_duration(1000.,'ethereum'))
json.dump({'policies':res,'worst_blocks_1000eth':{str(k):v for k,v in tab.items()},'ethereum':simulate_duration(1000.,'ethereum')},open(os.path.join(OUT,'e2_rational_declaration.json'),'w'),indent=1)
