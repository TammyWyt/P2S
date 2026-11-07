import json, subprocess, time
EP=['https://eth.drpc.org','https://eth.drpc.org','https://ethereum-rpc.publicnode.com']
V2='0xd78ad95fa46c994b6551d0da85fc275fe613ce37657fb8d5e3d130840159d822'
V3='0xc42079f94a6350d7e6235f29174924f928cc2ac818eb64fed8004e115fbcca67'
V4='0x40e9cecb9f5f1f1c5b9c97dec2917b7ee92e57ba5563708daca94dd84ad7112f'
def rpc(m,p):
    for t in range(12):
        try:
            b=json.dumps({"jsonrpc":"2.0","id":1,"method":m,"params":p})
            d=json.loads(subprocess.run(['curl','-s','--fail','-m','45','-H','content-type: application/json','-d',b,EP[t%3]],capture_output=True,timeout=60,check=True).stdout)
            if d.get('result') is not None: return d['result']
        except Exception: pass
        time.sleep(1+t)
    raise RuntimeError((m,p))
def sw(i): return i if i<2**255 else i-2**256
def label(l):
    t=l['topics'][0]; d=l['data'][2:]; w=lambda i:int(d[64*i:64*(i+1)],16)
    if t==V2: return [l['address'].lower(),0 if w(0)>0 else 1,2,w(0) or w(1)]
    if t==V3: return [l['address'].lower(),0 if sw(w(0))>0 else 1,3,abs(sw(w(0)))]
    if t==V4: return [l['topics'][1],0 if sw(w(0))<0 else 1,4,abs(sw(w(0)))]
