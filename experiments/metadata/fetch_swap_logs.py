#!/usr/bin/env python3
# formerly E1 fetch (scripts/experiments); run from the repo root.
"""Fetch every Uniswap-V2-style Swap/Sync and V3 Swap log in the paper's 1,004-block
window, plus token0 of each V2 pool. Real pool/direction/amount labels for E1."""
import json, os, time, urllib.request
from concurrent.futures import ThreadPoolExecutor
OUT=os.path.join(os.path.dirname(__file__),'cache')
EP=['https://eth.drpc.org','https://rpc.flashbots.net']
V2S='0xd78ad95fa46c994b6551d0da85fc275fe613ce37657fb8d5e3d130840159d822'
V3S='0xc42079f94a6350d7e6235f29174924f928cc2ac818eb64fed8004e115fbcca67'
SYNC='0x1c411e9a96e071241c2f21f7726b17ae89e3cab4c78be50e062b03a9fffbbad1'
A,B=18748996,18750000
def _curl(url,body=None):
    import subprocess
    a=['curl','-s','--fail','-m','60','-H','content-type: application/json']
    if body is not None: a+=['-X','POST','-d',body]
    return subprocess.run(a+[url],capture_output=True,timeout=90,check=True).stdout
def rpc(m,p):
    for t in range(14):
        try:
            d=json.loads(_curl(EP[t%2],json.dumps({"jsonrpc":"2.0","id":1,"method":m,"params":p})))
            if 'result' in d: return d['result']
        except Exception as e: print('retry',m,repr(e)[:120],flush=True)
        time.sleep(2+t*1.5)
    raise RuntimeError((m,p))
def chunk(a):
    return rpc('eth_getLogs',[{"fromBlock":hex(a),"toBlock":hex(min(a+24,B)),"topics":[[V2S,V3S,SYNC]]}])
CACHE=os.path.join(OUT,'swap_log_chunks'); os.makedirs(CACHE,exist_ok=True)
rs=[]
for a in range(A,B+1,25):                     # sequential and resumable: endpoints rate-limit
    p=os.path.join(CACHE,f'{a}.json')
    if not os.path.exists(p):
        json.dump(chunk(a),open(p,'w')); time.sleep(.4)
    rs.append(json.load(open(p)))
logs=[{'b':int(l['blockNumber'],16),'i':int(l['logIndex'],16),'tx':l['transactionHash'],'a':l['address'].lower(),'t':l['topics'][0],'d':l['data']} for r in rs for l in r]
print(len(logs))
v2={l['a'] for l in logs if l['t']==V2S}
def tok(a):
    try: return a,rpc('eth_call',[{"to":a,"data":"0x0dfe1681"},hex(B)])[-40:]
    except Exception: return a,None
with ThreadPoolExecutor(2) as x: t0=dict(x.map(tok,sorted(v2)))
json.dump({'logs':logs,'token0':t0},open(os.path.join(OUT,'swap_logs.json'),'w'))
print('pools',len(v2),'missing',sum(v is None for v in t0.values()))
