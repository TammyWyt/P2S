#!/usr/bin/env python3
"""E8: selective-reveal profitability on the 45 replayed sandwiches, the proposer-attacker worst
case (it controls ordering). A blind attempt on target i costs 2*F_res, F_res=phi*g_limit*
max(g_base,g_floor), phi=0.2. Worth attempting iff p*m_i > 2*F_res. m_i = replayed PoS gross profit
minus execution gas at the regime's base fee. Real m_i is an upper bound: the real attacker sized
its legs knowing the victim's amount. p comes from E7. Per-leg gas from the replay's own t8n use."""
import json, sys
sys.path.insert(0,'real/scripts')
from v2math import sandwich_profit
PHI=.2; GL=150_000
s=json.load(open('real/data/sandwiches.json')); T=[a for a in s['attacked_trades_v2'] if a['reserve_eth_wei']>0 and a['victim_weth_in_eth']>0 and a['front_weth_in_eth']>0]
fx=json.load(open('real/data/mev_measured_realized.json'))['per_fixture']
V={(v['block'],v['pool']):v for v in json.load(open('data/experiments/e7_victims.json'))}
GASPX=1.0   # measure_mev.GAS_PRICE, gwei
gross=[];bf=[]
for a,r in zip(T,fx):
    p,_=sandwich_profit(int(a['reserve_eth_wei']),int(a['reserve_token']),int(round(a['front_weth_in_eth']*1e18)),int(round(a['victim_weth_in_eth']*1e18)))
    gross.append(p/1e18); bf.append(V[(a['block'],a['pool'])]['bf']/1e9)
legs=[g-r['pos_mev_eth'] for g,r in zip(gross,fx)]
E7=json.load(open('data/experiments/e7_metadata.json')); ps=dict(best=E7['p_best_victims'],upper=E7['p_best_victims_ci95'][1],e1_low=.163,e1_high=.194)
EXEC=sum(legs)/len(legs)/(GASPX*1e-9)
R=[]
for nm,g,fl,per in (('45.1gwei',45.1,0,False),('0.12gwei_floor2',.12,2,False),('0.12gwei_nofloor',.12,0,False),('block_basefee_floor2',None,2,True)):
    for pn,p in ps.items():
        w=[];tot=0;sumpm=0;net=0
        for i,x in enumerate(gross):
            b=bf[i] if per else g; m=x-EXEC*b*1e-9; F=PHI*GL*max(b,fl)*1e-9; tot+=max(m,0)
            if p*m>2*F: w.append(i); sumpm+=p*m; net+=p*m-2*F
        R.append(dict(regime=nm,p_name=pn,p=p,F_res_eth=PHI*GL*max(g,fl)*1e-9 if g else None,worth=len(w),expected_extraction_eth=sumpm,expected_net_eth=net,m_total_eth=tot,share=sumpm/tot if tot else 0))
o=dict(n=len(gross),gross_total=sum(gross),replay_net_total=sum(r['pos_mev_eth'] for r in fx),exec_gas_units=EXEC,block_basefee_gwei=dict(min=min(bf),median=sorted(bf)[len(bf)//2],max=max(bf)),rows=R)
json.dump(o,open('data/experiments/e8_selective_reveal.json','w'),indent=1); print(json.dumps(o,indent=1))
