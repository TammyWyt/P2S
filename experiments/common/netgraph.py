# formerly e_net (scripts/experiments); run from the repo root.
"""Shared helpers: netsim.Net's gossip as a fixed weighted digraph, so all-pairs arrival
times come from one Dijkstra. Edge u->v = PROC + (rank+1)*serial + one_way(u,v), the same
per-hop model as Net.gossip, with link jitter drawn once per net. No queueing across
concurrent messages; e10 measures that separately."""
import os, sys
sys.path.insert(0,os.path.join(os.path.dirname(os.path.abspath(__file__)),'..','..','scripts','simulation'))
import numpy as np, netsim as ns
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import dijkstra
def apsp(net,size,part=None,delta=0.0,sources=None):
    n=net.n; ser=size*8/ns.BW_BPS; r=[];c=[];d=[]
    for u in range(n):
        for i,v in enumerate(net.peers[u]):
            w=ns.PROC_S+(i+1)*ser+ns.lat_ms(net.region[u],net.region[v])/1000*(1+net.rng.uniform(-ns.JITTER,ns.JITTER))
            if part is not None and part[u]!=part[v]: w+=delta
            r.append(u);c.append(v);d.append(w)
    return dijkstra(csr_matrix((d,(r,c)),shape=(n,n)),directed=True,indices=sources)
def wilson(k,n,z=1.96):
    if n==0: return [0,1]
    p=k/n; a=p+z*z/2/n; b=z*((p*(1-p)+z*z/4/n)/n)**.5; c=1+z*z/n
    return [max(0,(a-b)/c),min(1,(a+b)/c)]
