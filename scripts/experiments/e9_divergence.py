#!/usr/bin/env python3
"""E9: reveal-set divergence under adversarial delivery, N=1000, D=8, K=150, 1000 slots per
setting (20 nets x 50 slots). Local E: v includes a reveal held by the deadline. Rule (App.
A.3): holders report at the deadline, v includes a reveal iff >=f+1 reports reach it within
window W. Divergence = honest validators close different E.
 a  straddle: one reveal released delta before the deadline; a* = timed so exactly f+1+x hold it
 b  partial send: reveal handed to a q-fraction, delta before the deadline, then gossiped
 c  delayed partition: q of validators, cross links +Delta ms, 150 honest reveals at t=0
 d  Byzantine report timing (not in A.3's fixed-window-free model): f validators back a reveal
    and release their reports so they straddle the window. Tests a timed window, which is what
    an in-slot deployment needs; Prop. 4 assumes reliable broadcast has terminated."""
import json, os, sys
from multiprocessing import Pool
sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
from e_net import *
N=1000;f=(N-1)//3;K=150;MT=371;NETS=20;SL=50
REPS={'full_4950B':K*33,'bitmap_115B':115}
WM=(1.4,2.0,3.0)
DA=(0,10,25,50,75,100,125,150,175,200,250,300)
def dec(hold,dR,W,t=None):
    a=dR[np.ix_(np.flatnonzero(hold),np.arange(N))]<=W
    return a.sum(0)>=f+1
def worker(i):
    net=ns.Net(N,seed=104729*(i+1)+N); R=np.random.default_rng(i); M=apsp(net,MT)
    p90=np.percentile(M,90,axis=1).mean(); D=1.4*p90; out=[]
    def add(k,local,rule,inc): out.append((k,int(local),int(rule),float(inc)))
    for rn,rs in REPS.items():
        dR=apsp(net,rs); pr=np.percentile(dR,90,axis=1).mean()
        for wm in WM:
            W=wm*pr; tag=f'{rn}|W={wm}'
            for s in range(SL):
                src=R.integers(N); o=np.sort(M[src])
                for d in DA:
                    h=(D-d/1000+M[src])<=D; inc=dec(h,dR,W)
                    add(f'a|delta={d}|{tag}',0<h.sum()<N,0<inc.sum()<N,inc.mean())
                for x in (0,1,5,20):
                    t=o[f+x]+1e-9; h=M[src]<=t; inc=dec(h,dR,W)
                    add(f'a*|holders=f+1+{x}|{tag}',0<h.sum()<N,0<inc.sum()<N,inc.mean())
                for q in (.1,.25,.334,.5,.75):
                    S=R.choice(N,int(q*N),replace=False); m=M[S].min(0)
                    for d in (0,25,50,100):
                        h=m<=d/1000; inc=dec(h,dR,W)
                        add(f'b|q={q}|delta={d}|{tag}',0<h.sum()<N,0<inc.sum()<N,inc.mean())
                # d: honest holders h0, f Byzantine reports released at offset so they straddle D+W
                B=R.choice(N,f,replace=False); hon=np.setdiff1d(np.arange(N),B)
                for h0 in (1,50):
                    H=R.choice(hon,h0,replace=False)
                    for frac in (.5,.8,1.0):
                        base=(dR[H]<=W).sum(0)
                        t=W-frac*np.percentile(dR[B],90,axis=1).mean()      # release time
                        cnt=base+((t+dR[B])<=W).sum(0); inc=cnt[hon]>=f+1
                        add(f'd|h={h0}|release_frac={frac}|{tag}',True,0<inc.sum()<len(hon),inc.mean())
        for q in (.10,.20,.33):
            part=np.zeros(N,bool); part[R.choice(N,int(q*N),replace=False)]=True
            for dl in (100,300,1000):
                Mp=apsp(net,MT,part,dl/1000); dRp=apsp(net,rs,part,dl/1000)
                prp=np.percentile(dRp,90,axis=1).mean(); pr0=pr
                for wm in WM:
                    W=wm*pr0; tag=f'{rn}|W={wm}'
                    for s in range(SL):
                        ss=R.integers(N,size=K); loc=rule=False; ex=0
                        H=Mp[ss]<=D
                        cnt=(H.astype(np.int32)@(dRp<=W).astype(np.int32))
                        inc=cnt>=f+1
                        rule=bool(((inc.sum(1)>0)&(inc.sum(1)<N)).any()); loc=bool(((H.sum(1)>0)&(H.sum(1)<N)).any())
                        add(f'c|q={q}|Delta={dl}|{tag}',loc,rule,inc.mean())
    return out
if __name__=='__main__':
    with Pool(9) as p: res=p.map(worker,range(NETS))
    A={}
    for r in res:
        for k,l,u,i in r:
            e=A.setdefault(k,[0,0,0,0.0]); e[0]+=1;e[1]+=l;e[2]+=u;e[3]+=i
    rows=[dict(setting=k,slots=v[0],local_div=v[1]/v[0],rule_div=v[2]/v[0],rule_ci95=wilson(v[2],v[0]),rule_included=v[3]/v[0]) for k,v in sorted(A.items())]
    json.dump(dict(N=N,f=f,K=K,D=8,nets=NETS,slots_per_net=SL,rows=rows),open('data/experiments/e9_divergence.json','w'),indent=1)
    print('e9 done',len(rows))
