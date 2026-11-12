#!/usr/bin/env python3
# formerly E3b (scripts/experiments); run from the repo root.
"""E3b: MEASURED disagreement under the f+1 rule. Every holder's signed report is gossiped
on the paper's network; each validator counts only reports reaching it inside the report
window. Disagreement = some validators see >=f+1 reports and some see fewer."""
import json, os, sys, statistics as st
sys.path.insert(0,os.path.join(os.path.dirname(__file__),'..','..','scripts','simulation'))
import netsim as ns
N=1000; f=(N-1)//3; K=150; MT=371; REP=K*33; SEEDS=24
out=[]
for off in (150,175,200):
  for slack in (1.4,2.0):
    dis=inc=0; w=[]
    for s in range(SEEDS):
        net=ns.Net(N,seed=15485863*(s+1)+off); recv,_,_=net.gossip(s%N,MT)
        holders=[v for v in range(N) if recv.get(v,9e9)<=off/1000]
        cnt=[0]*N; p=[]
        for h in holders:
            r,_,_=net.gossip(h,REP); p.append(r)
        W=(st.mean(net.pct(r,.9) for r in p[:20])*slack) if p else 0
        for r in p:
            for v,t in r.items():
                if t<=W: cnt[v]+=1
        yes=sum(c>=f+1 for c in cnt); w.append(W)
        dis+= 0<yes<N; inc+= yes==N
    row={'release_ms':off,'window_x_p90':slack,'window_ms':1000*st.mean(w),'disagree_rate':dis/SEEDS,'all_include_rate':inc/SEEDS,'all_exclude_rate':1-(dis+inc)/SEEDS,'seeds':SEEDS}
    print(row,flush=True); out.append(row)
json.dump(out,open('experiments/reveal_agreement/data/threshold_measured.json','w'),indent=1)
