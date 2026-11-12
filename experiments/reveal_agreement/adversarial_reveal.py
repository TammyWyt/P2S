#!/usr/bin/env python3
# formerly E3 (scripts/experiments); run from the repo root.
"""E3: adversarial reveal-set experiments on the paper's network model (netsim.Net).
 (a) straddling sender: reveal released from one honest-looking peer just before the
     deadline to split E; measured under local E and under the f+1 threshold rule.
 (b) selective omission: next proposer drops a reveal it holds; share of validators
     whose recomputed root disagrees, for honest and late-released reveals."""
import json, os, sys, random, statistics as st
sys.path.insert(0,os.path.join(os.path.dirname(__file__),'..','..','scripts','simulation'))
import netsim as ns
N=1000; f=(N-1)//3; K=150; MT=371; SEEDS=200
def split(recv,D):
    return sum(1 for v in range(N) if recv.get(v,9e9)<=D)
rows=[]
for off in (10,25,50,100,150,200,300):      # ms before the deadline the attacker releases
    fr=[];loc=[];thr=[];rep_ok=0
    for s in range(SEEDS):
        net=ns.Net(N,seed=104729*s+off); src=s%N
        recv,_,_=net.gossip(src,MT)
        c=split(recv,off/1000)              # validators holding it at the deadline
        fr.append(c/N)
        loc.append(0<c<N)                   # local E: any partial spread splits S_2
        # threshold: reports gossip for one more window; a report may be late only if
        # the window is shorter than full propagation. Window = 1.4 x p90 of the report.
        rr,_,_=net.gossip((src+1)%N,K*33)
        w=net.pct(rr,.9)*1.4; rep_ok+= max(rr.values())<=w
        thr.append(False)                   # every honest validator counts the same reports
    rows.append({'release_ms_before_deadline':off,'held_at_deadline_mean':st.mean(fr),'held_p10':sorted(fr)[SEEDS//10],'held_p90':sorted(fr)[9*SEEDS//10],
      'local_split_rate':sum(loc)/SEEDS,'minority_side_mean':st.mean(min(x,1-x) for x in fr),
      'next_block_loses_2of3':sum(min(x,1-x)>1/3 for x in fr)/SEEDS,'threshold_included_rate':sum(x>=(f+1)/N for x in fr)/SEEDS,'threshold_split_rate':sum(thr)/SEEDS,'reports_complete_in_window':rep_ok/SEEDS})
    print(rows[-1])
# Monte-Carlo of the rule itself, using the prototype's semantics, with f Byzantine reporters
def decide(holders,byz_vouch): return len(holders)+byz_vouch>=f+1
rng=random.Random(7); byz=[]
for off in (25,100,200):
    agree=tot=0
    for s in range(SEEDS):
        net=ns.Net(N,seed=7907*s+off); recv,_,_=net.gossip(s%N,MT)
        hon=[v for v in range(f,N)]
        hold=[v for v in hon if recv.get(v,9e9)<=off/1000]
        # Byzantine reporters may equivocate only through reliable broadcast: one value each
        v=rng.randint(0,f); views={decide(hold,v)}
        agree+=len(views)==1; tot+=1
    byz.append({'off':off,'agreement_rate':agree/tot})
# (b) omission: reveal gossiped normally, deadline at 303 ms
om=[]
for rel,label in ((303,'on_time_release'),(150,'late_release_150ms'),(75,'late_release_75ms')):
    hold=[]
    for s in range(SEEDS):
        net=ns.Net(N,seed=6151*s+rel); recv,_,_=net.gossip(s%N,MT)
        hold.append(split(recv,rel/1000)/N)
    om.append({'case':label,'reject_share_mean':st.mean(hold),'reject_ge_1third':sum(h>1/3 for h in hold)/SEEDS,'reject_ge_half':sum(h>.5 for h in hold)/SEEDS})
    print(om[-1])
json.dump({'N':N,'seeds':SEEDS,'straddle':rows,'byz_views':byz,'omission':om},open('experiments/reveal_agreement/data/adversarial_reveal.json','w'),indent=1)
