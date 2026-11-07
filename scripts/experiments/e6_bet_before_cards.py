#!/usr/bin/env python3
"""E6: the bet-before-cards bound on the 45 real V2 sandwiches. An attacker hits with
probability p (E1's measured pool+direction hit rate) and forfeits F_res on each of k=2
withheld legs on a miss, so a target is worth attempting iff p*m > (1-p)*k*F_res."""
import json, os, sys
sys.path.insert(0,os.path.join(os.path.dirname(__file__),'..','..','real','scripts'))
from v2math import sandwich_profit
s=json.load(open('real/data/sandwiches.json'))
T=[a for a in s['attacked_trades_v2'] if a['reserve_eth_wei']>0 and a['victim_weth_in_eth']>0 and a['front_weth_in_eth']>0]
W=10**18; m=[]
for a in T:
    p,_=sandwich_profit(int(a['reserve_eth_wei']),int(a['reserve_token']),int(a['front_weth_in_eth']*W),int(a['victim_weth_in_eth']*W))
    m.append(max(p,0)/W)
tot=sum(m); out=[]
for g in (45,20,8,2):
    F=0.2*150_000*g*1e-9
    for p in (0.163,0.194):
        w=[x for x in m if p*x>(1-p)*2*F]
        net=sum(p*x-(1-p)*2*F for x in w)
        out.append(dict(gwei=g,F_res=F,p=p,worth=len(w),net_eth=net,share=net/tot))
r=dict(n=len(m),total_eth=tot,max_eth=max(m),rows=out)
print(json.dumps(r,indent=1)); json.dump(r,open('data/experiments/e6_bet_before_cards.json','w'),indent=1)
