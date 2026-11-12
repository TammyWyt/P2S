#!/usr/bin/env python3
# formerly E1b (scripts/experiments); run from the repo root.
import json, subprocess, time
from concurrent.futures import ThreadPoolExecutor
d=json.load(open('experiments/metadata/cache/swap_logs.json')); P=sorted(d['token0'])
EP=['https://eth.drpc.org','https://rpc.flashbots.net']
def t1(a):
    for t in range(8):
        try:
            b=json.dumps({"jsonrpc":"2.0","id":1,"method":"eth_call","params":[{"to":a,"data":"0xd21220a7"},hex(18750000)]})
            r=json.loads(subprocess.run(['curl','-s','--fail','-m','30','-H','content-type: application/json','-X','POST','-d',b,EP[t%2]],capture_output=True,check=True).stdout)
            if 'result' in r: return a,r['result'][-40:]
        except Exception: pass
        time.sleep(1+t)
    return a,None
with ThreadPoolExecutor(4) as x: r=dict(x.map(t1,P))
json.dump(r,open('experiments/metadata/data/token1.json','w')); print(len(r),sum(v is None for v in r.values()))
