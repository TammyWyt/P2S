#!/usr/bin/env python3
"""E7b: find the 45 victim txs in their blocks, then fetch each sender's last 100 txs strictly
before the target block (Blockscout txlist) and their swap labels (receipts). Resumable."""
import json, os, subprocess, sys, time, glob
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0,'scripts/experiments')
from e7_labels import label, rpc
OUT='data/experiments/_e7h'; os.makedirs(OUT,exist_ok=True)
s=json.load(open('real/data/sandwiches.json')); V=[]
for a in s['attacked_trades_v2']:
    B=json.load(open(f"data/experiments/_e7/{a['block']}.json")); w=int(round(a['victim_weth_in_eth']*1e18)); hit=[]
    for r in B['rows']:
        if r['s']==a['attacker']: continue
        for L in r['L']:
            if L[0]==a['pool'] and L[2]==2 and abs(L[3]-w)<=max(10**6,w//10**9): hit.append((r,L))
    V.append(dict(block=a['block'],pool=a['pool'],bf=B['bf'],found=len(hit),tx=hit[0][0] if hit else None,label=hit[0][1][:2] if hit else None))
print('victims',len(V),'found',sum(v['found']>0 for v in V),'multi',sum(v['found']>1 for v in V),flush=True)
json.dump(V,open('data/experiments/e7_victims.json','w'))
def hist(v):
    if not v['tx']: return
    p=f"{OUT}/h_{v['block']}_{v['tx']['s']}.json"
    if os.path.exists(p): return
    a=v['tx']['s']; q=''; out=[]; trunc=True
    for pg in range(600):
        u=f"https://eth.blockscout.com/api/v2/addresses/{a}/transactions?filter=from{q}"
        d=None
        for t in range(8):
            try:
                d=json.loads(subprocess.run(['curl','-s','--fail','-m','40',u],capture_output=True,timeout=60,check=True).stdout); break
            except Exception: time.sleep(3+3*t)
        if d is None: print('fail',a,pg,flush=True); return
        for x in d.get('items',[]):
            if x['block_number']<v['block']: out.append(dict(h=x['hash'],b=x['block_number'],gas=int(x.get('gas_limit') or 0),s=a))
        np_=d.get('next_page_params')
        if len(out)>=100 or not np_: trunc=False; break
        q='&'+'&'.join(f'{k}={w}' for k,w in np_.items() if w is not None); time.sleep(.4)
    if trunc: print('truncated',a,flush=True)
    json.dump(out[:100],open(p,'w'))
for v in V: hist(v); time.sleep(1.5)
H=set()
for p in glob.glob(OUT+'/h_*.json'):
    H|={x['h'] for x in json.load(open(p)) if x['s']==os.path.basename(p)[:-5].split('_')[2]}
print('history txs',len(H),flush=True)
def rc(h):
    p=f'{OUT}/r_{h}.json'
    if os.path.exists(p): return
    r=rpc('eth_getTransactionReceipt',[h]); json.dump([x for x in (label(l) for l in r['logs'] if l['topics']) if x] if int(r['status'],16) else [],open(p,'w'))
with ThreadPoolExecutor(4) as ex:
    for i,_ in enumerate(ex.map(rc,sorted(H))):
        if i%500==0: print(i,flush=True)
print('done',flush=True)
