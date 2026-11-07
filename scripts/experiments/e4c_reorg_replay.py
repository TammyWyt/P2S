#!/usr/bin/env python3
"""E4c: the 45 real V2 sandwiches re-run in the reorg scenario, with bit-exact V2 math.
Unbound reveal: the attacker holds the public opening on its fork and places both legs
around the victim. Fork-bound: the opening is invalid there, the victim never executes."""
import json, os, sys
sys.path.insert(0,os.path.join(os.path.dirname(__file__),'..','..','real','scripts'))
from v2math import sandwich_profit
s=json.load(open('real/data/sandwiches.json'))
T=[a for a in s['attacked_trades_v2'] if a['reserve_eth_wei']>0 and a['victim_weth_in_eth']>0 and a['front_weth_in_eth']>0]
W=10**18; u=b=0; pos=0
for a in T:
    Re,Rt=int(a['reserve_eth_wei']),int(a['reserve_token']); V=int(a['victim_weth_in_eth']*W); F=int(a['front_weth_in_eth']*W)
    p,_=sandwich_profit(Re,Rt,F,V); u+=max(p,0)
    q,_=sandwich_profit(Re,Rt,F,0); b+=max(q,0); pos+=q<0
r={'n':len(T),'unbound_reorg_extracted_eth':u/W,'forkbound_extracted_eth':b/W,'legs_alone_lose_money':pos}
print(r); json.dump(r,open('data/experiments/e4c_reorg_replay.json','w'),indent=1)
