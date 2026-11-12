#!/usr/bin/env python3
# formerly E10 (scripts/experiments); run from the repo root.
"""E10: extra round of the set-union rule at N=1000, K=150, 100 runs. Every validator gossips
a report at the deadline; a validator can decide E once it holds 2f+1 reports (it cannot wait
for Byzantine ones, and f+1 of 2f+1 are needed to admit). Measured: time until 90% of
validators hold 2f+1 reports, with every validator's uplink a single 50 Mbps FIFO shared by all
N concurrent reports. The idle-network figure (no queueing) is printed beside it.
Formats: full 150 x 33 B ref list (A.3 as written) vs a bitmap over S1's positions + BLS sig."""
import json, heapq, random, sys, os
from multiprocessing import Pool
sys.path.insert(0,os.path.join(os.path.dirname(os.path.abspath(__file__)),'..','common'))
from netgraph import *
N=1000;f=(N-1)//3;Q=2*f+1;K=150;RUNS=100
FMT={'full_4950B':4950,'bitmap_115B':115}
def contended(net,size):
    ser=size*8/ns.BW_BPS; rng=random.Random(net.n); busy=[0.0]*N; seen=[bytearray(N) for _ in range(N)]
    got=[[] for _ in range(N)]; pq=[]; push=heapq.heappush; pop=heapq.heappop
    peers=net.peers; reg=net.region; msgs=0; PROC=ns.PROC_S; lat=ns.lat_ms; J=ns.JITTER; uni=rng.uniform
    for v in range(N): pq.append((0.0,v,v))
    heapq.heapify(pq)
    while pq:
        t,r,v=pop(pq)
        if seen[v][r]: continue
        seen[v][r]=1; got[v].append(t)
        b=max(busy[v],t+PROC)
        sv=seen; rv=reg[v]
        for u in peers[v]:
            b+=ser; msgs+=1
            if not sv[u][r]: push(pq,(b+lat(rv,reg[u])/1000*(1+uni(-J,J)),r,u))
        busy[v]=b
    dec=sorted(g[Q-1] for g in got)
    return dec[int(.9*N)],dec[-1],msgs*size/1e6
def run(a):
    fmt,s=a; size=FMT[fmt]; net=ns.Net(N,seed=7907*s+N)
    d=np.sort(apsp(net,size),axis=0)                # idle: each report alone on the network
    idle=float(np.percentile(d[Q-1],90))
    t90,tmax,mb=contended(net,size)
    return fmt,idle,t90,tmax,mb
if __name__=='__main__':
    jobs=[(k,s) for k in FMT for s in range(RUNS)]
    with Pool(9) as p: R=p.map(run,jobs,chunksize=1)
    o={}
    for k in FMT:
        X=np.array([r[1:] for r in R if r[0]==k]); m=X.mean(0); ci=1.96*X.std(0,ddof=1)/RUNS**.5
        o[k]=dict(size_B=FMT[k],idle_t90_s=m[0],idle_ci=ci[0],contended_t90_s=m[1],contended_ci=ci[1],contended_last_s=m[2],gossip_MB_total=m[3],gossip_MB_per_validator=m[3]/N,unique_MB_per_validator=FMT[k]*N/1e6)
    json.dump(dict(N=N,f=f,K=K,runs=RUNS,decide_at=Q,formats=o),open('experiments/reveal_agreement/data/setunion_latency.json','w'),indent=1)
    print(json.dumps(o,indent=1))
