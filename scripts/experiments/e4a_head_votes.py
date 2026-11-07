#!/usr/bin/env python3
"""E4a: real mainnet head-vote share per slot, read from the beacon chain. For each slot s
with a block, unions the aggregation bits of attestations voting for that block's root
in slot s, included in blocks s+1..s+2, against the slot's committee size. Also counts
missed slots. This is what a wallet's attestation gate would have observed."""
import json, os, sys, time, urllib.request
from concurrent.futures import ThreadPoolExecutor
B='https://ethereum-beacon-api.publicnode.com'
def _curl(url,body=None):
    import subprocess
    a=['curl','-s','--fail','-m','60','-H','content-type: application/json']
    if body is not None: a+=['-X','POST','-d',body]
    return subprocess.run(a+[url],capture_output=True,timeout=90,check=True).stdout
def get(p):
    for t in range(8):
        try: return json.loads(_curl(B+p))
        except Exception as e:
            print('retry',p[:60],repr(e)[:100],flush=True); time.sleep(3+2*t)
    return None
head=int(get('/eth/v1/beacon/headers/finalized')['data']['header']['message']['slot'])
def bits(h,):
    b=bytes.fromhex(h[2:]); return b
WIN=[head-64*(1+i*2) for i in range(3)]     # recent epochs: the node serves committees for retained states only
res=[]
for start in WIN:
    start-=start%32                          # epoch-aligned so one committees call covers it
    cm={}
    c=get(f'/eth/v1/beacon/states/finalized/committees?epoch={start//32}')
    c2=get(f'/eth/v1/beacon/states/finalized/committees?epoch={start//32+1}')
    if c is None: print('no committees for',start,flush=True); continue
    for x in (c['data']+(c2['data'] if c2 else [])): cm.setdefault(int(x['slot']),{})[int(x['index'])]=len(x['validators'])
    hdr={}
    def h(s):
        d=get(f'/eth/v1/beacon/headers/{s}'); return s,(d['data']['root'] if d else None)
    with ThreadPoolExecutor(2) as ex: hdr=dict(ex.map(h,range(start,start+66)))
    def at(s):
        d=get(f'/eth/v2/beacon/blocks/{s}/attestations'); return s,(d['data'] if d else [])
    with ThreadPoolExecutor(2) as ex: ats=dict(ex.map(at,range(start,start+66)))
    votes={}
    for s,L in ats.items():
        for a in L:
            sl=int(a['data']['slot'])
            if sl<start or sl>=start+64 or hdr.get(sl) is None or a['data']['beacon_block_root']!=hdr[sl]: continue
            cb=bytes.fromhex(a['committee_bits'][2:]); idx=[i for i in range(len(cb)*8) if cb[i//8]>>(i%8)&1]
            ab=bytes.fromhex(a['aggregation_bits'][2:]); off=0
            for i in idx:
                n=cm[sl].get(i,0)
                st=votes.setdefault((sl,i),set())
                for k in range(n):
                    if ab[(off+k)//8]>>((off+k)%8)&1: st.add(k)
                off+=n
    for s in range(start,start+64):
        tot=sum(cm.get(s,{}).values())
        if hdr.get(s) is None: res.append({'slot':s,'missed':True}); continue
        got=sum(len(v) for (sl,i),v in votes.items() if sl==s)
        res.append({'slot':s,'missed':False,'share':got/tot if tot else None})
    print(start,len(res),flush=True)
sh=sorted(r['share'] for r in res if not r['missed'] and r['share'] is not None)
q=lambda p:sh[int(p*(len(sh)-1))]
out={'slots':len(res),'missed':sum(r['missed'] for r in res),'median':q(.5),'p10':q(.1),'p1':q(.01),'min':sh[0],
 'share_ge':{str(t):sum(x>=t for x in sh)/len(sh) for t in (.5,.6,.7,.8,.9)},'below_20pct':sum(x<.2 for x in sh)/len(sh),'rows':res}
json.dump(out,open(os.path.join(os.path.dirname(__file__),'..','..','data','experiments','e4a_head_votes.json'),'w'))
print({k:v for k,v in out.items() if k!='rows'})
