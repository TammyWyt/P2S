#!/usr/bin/env python3
# formerly E7 fetch (scripts/experiments); run from the repo root.
"""E7 data: for the paper's 1,000-block window and the detector's 400 sampled blocks, fetch
sender, nonce, gas, fee fields and swap labels (pool, direction) for every tx with a V2/V3/V4
Swap log, plus the 10,248 DEX swaps of Sec. 6.1 whether or not they emit one. Resumable."""
import json, os, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0,'scripts')
from revert_cost_analysis import DEX_ROUTERS
OUT='experiments/metadata/cache/swap_label_blocks'; os.makedirs(OUT,exist_ok=True)
EP=['https://eth.drpc.org','https://eth.drpc.org','https://ethereum-rpc.publicnode.com']
V2='0xd78ad95fa46c994b6551d0da85fc275fe613ce37657fb8d5e3d130840159d822'
V3='0xc42079f94a6350d7e6235f29174924f928cc2ac818eb64fed8004e115fbcca67'
V4='0x40e9cecb9f5f1f1c5b9c97dec2917b7ee92e57ba5563708daca94dd84ad7112f'
def rpc(m,p):
    for t in range(12):
        try:
            b=json.dumps({"jsonrpc":"2.0","id":1,"method":m,"params":p})
            o=subprocess.run(['curl','-s','--fail','-m','45','-H','content-type: application/json','-d',b,EP[t%3]],capture_output=True,timeout=60,check=True).stdout
            d=json.loads(o)
            if d.get('result') is not None: return d['result']
        except Exception as e: pass
        time.sleep(1+t)
    raise RuntimeError((m,p))
def sw(i): return i if i<2**255 else i-2**256
def label(l):
    t=l['topics'][0]; d=l['data'][2:]; w=lambda i:int(d[64*i:64*(i+1)],16)
    if t==V2: return [l['address'].lower(),0 if w(0)>0 else 1,2,w(0) or w(1)]
    if t==V3: return [l['address'].lower(),0 if sw(w(0))>0 else 1,3,abs(sw(w(0)))]
    if t==V4: return [l['topics'][1],0 if sw(w(0))<0 else 1,4,abs(sw(w(0)))]
def one(n):
    p=f'{OUT}/{n}.json'
    if os.path.exists(p): return
    h=hex(n); B=rpc('eth_getBlockByNumber',[h,True]); R=rpc('eth_getBlockReceipts',[h])
    rm={r['transactionHash']:r for r in R}; rows=[]
    for t in B['transactions']:
        r=rm[t['hash']]; L=[x for x in (label(l) for l in r['logs'] if l['topics'] and l['topics'][0] in (V2,V3,V4)) if x]
        to=(t.get('to') or '').lower()
        if not L and to not in DEX_ROUTERS: continue
        rows.append(dict(h=t['hash'],s=t['from'].lower(),to=to,nonce=int(t['nonce'],16),gas=int(t['gas'],16),gu=int(r['gasUsed'],16),
          st=int(r['status'],16),maxfee=int(t.get('maxFeePerGas',t.get('gasPrice')),16),tip=int(t.get('maxPriorityFeePerGas','0x0'),16),L=L))
    json.dump(dict(n=n,bf=int(B['baseFeePerGas'],16),ts=int(B['timestamp'],16),rows=rows),open(p+'.tmp','w')); os.replace(p+'.tmp',p)
s=json.load(open('real/data/sandwiches.json'))
win=[b for w in s['windows'] for b in range(w['block']-9,w['block']+1)]
blocks=sorted(set(win)|set(a['block'] for a in s['attacked_trades_v2'])|set(range(25245959,25246959)))
print(len(blocks),flush=True)
with ThreadPoolExecutor(4) as ex:
    for i,_ in enumerate(ex.map(one,blocks)):
        if i%100==0: print(i,flush=True)
print('done',flush=True)
