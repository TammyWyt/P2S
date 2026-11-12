# formerly E0 (scripts/experiments); run from the repo root.
"""Public-field fingerprinting: can an attacker tell DEX-router traffic from what a PHT exposes?
Strict time split, sender history is prequential (only earlier blocks). Naive-Bayes log-odds."""
import json, math, re, sys, collections as C
sys.path.insert(0,'/Users/tammy/Code/P2S/scripts')
src=open('/Users/tammy/Code/P2S/scripts/revert_cost_analysis.py').read()
R=dict(re.findall(r'"(0x[0-9a-f]{40})":\s*"([^"]+)"',src[src.index('DEX_ROUTERS = {'):src.index('}',src.index('DEX_ROUTERS = {'))]))
R.update({'0x80a64c6d7f12c47b7c66c5b4e20e72bc1fcd5d9e':'Maestro','0x3328f7f4a1d1c57c35df56bbf0c9dcafca309c49':'BananaGun'})
def glb(g): return int(round(math.log2(max(g,1))*4))          # quarter-octave gas-limit bucket
def nb(n): return 0 if n==0 else 1+min(int(math.log2(n+1)),12)
class NB:
    def __init__(s,k): s.n=C.Counter(); s.c=[C.defaultdict(C.Counter) for _ in range(k)]; s.vals=[set() for _ in range(k)]
    def fit(s,X,y):
        for x,l in zip(X,y):
            s.n[l]+=1
            for i,v in enumerate(x): s.c[i][l][v]+=1; s.vals[i].add(v)
    def score(s,x):
        o=math.log((s.n[1]+1)/(s.n[0]+1))
        for i,v in enumerate(x):
            V=len(s.vals[i])+1
            o+=math.log((s.c[i][1][v]+.5)/(s.n[1]+.5*V))-math.log((s.c[i][0][v]+.5)/(s.n[0]+.5*V))
        return o
def auc(sc,y):
    p=sorted(zip(sc,y)); r=0;i=0;n=len(p);pos=sum(y);neg=n-pos
    while i<n:
        j=i
        while j<n and p[j][0]==p[i][0]: j+=1
        rk=(i+j+1)/2
        r+=rk*sum(l for _,l in p[i:j]); i=j
    return (r-pos*(pos+1)/2)/(pos*neg)
def report(name,sc,y):
    pos=sum(y);n=len(y);o=sorted(zip(sc,y),reverse=True)
    res={'n':n,'base_rate':pos/n,'auc':auc(sc,y)}
    for q in (.01,.05,.10):
        k=int(n*q); res[f'prec@top{int(q*100)}%']=sum(l for _,l in o[:k])/k
    t=0
    best=None
    for i,(s,l) in enumerate(o,1):
        t+=l
        if best is None and t>=.5*pos: best=t/i
    res['prec@recall50']=best
    # posterior-threshold rule at 0.5
    k=[l for s,l in o if s>0]; res['flagged_frac']=len(k)/n; res['prec@flag']=sum(k)/max(len(k),1); res['recall@flag']=sum(k)/pos
    print(name,{a:(round(b,3) if isinstance(b,float) else b) for a,b in res.items()})
    return res
# ---- 2023: sender, nonce, gas limit, gas price
d=json.load(open('/Users/tammy/Code/P2S/data/ethereum_blocks_cache.json'))
ks=sorted([k for k in d if k.isdigit()],key=int); cut=ks[int(len(ks)*.7)]
hist=C.defaultdict(lambda:[0,0]); lastto={}
rows=[]; 
for k in ks:
    bf=d[k]['base_fee']; pend=[]
    for t in d[k]['transactions']:
        to=(t.get('to') or '').lower(); y=int(to in R); s=t['from'].lower(); h=hist[s]
        cls='fresh' if h[0]==0 else ('never' if h[1]==0 else ('always' if h[1]==h[0] else 'mixed'))
        tip=max(int(t['gasPrice'])-bf,0)/1e9
        rows.append((int(k),y,glb(t['gas']),nb(int(t['nonce'])),cls,int(math.log2(tip+1)*2),to,lastto.get(s)))
        pend.append((s,y,to))
    for s,y,to in pend:                     # history updates only after the block closes
        hist[s][0]+=1; hist[s][1]+=y; lastto[s]=to
tr=[r for r in rows if r[0]<int(cut)]; te=[r for r in rows if r[0]>=int(cut)]
out={}
for name,f in {'gas only':lambda r:(r[2],),'gas+tip+nonce (fresh-sender view)':lambda r:(r[2],r[3],r[5]),'all public incl sender history':lambda r:(r[2],r[3],r[5],r[4])}.items():
    m=NB(len(f(tr[0]))); m.fit([f(r) for r in tr],[r[1] for r in tr])
    sc=[m.score(f(r)) for r in te]; out[name]=report('2023 '+name,sc,[r[1] for r in te])
    if 'all' in name:
        for c in ('fresh','never','mixed','always'):
            ii=[i for i,r in enumerate(te) if r[4]==c]; y=[te[i][1] for i in ii]
            print('   sender class',c,'n',len(ii),'share of test',round(len(ii)/len(te),3),'dex rate',round(sum(y)/len(y),3), 'share of test dex',round(sum(y)/sum(r[1] for r in te),3))
# which router, for repeat senders
dx=[r for r in te if r[1]]; rep=[r for r in dx if r[7]]; print('dex test txs',len(dx),'with prior sender',len(rep),'same `to` as sender last tx',round(sum(r[6]==r[7] for r in rep)/len(rep),3))
top=C.Counter(R[r[6]] for r in dx).most_common(4); print('router mix',[(a,round(b/len(dx),3)) for a,b in top])
# ---- 2026: no sender in cache, gas limit + priority only
r=json.load(open('/Users/tammy/Code/P2S/data/revert_receipts_cache.json'))
rk=sorted([k for k in r if k.isdigit()],key=int); cut=rk[int(len(rk)*.7)]
Rn=set(R); names={'UniversalRouter','UniswapV2Router02','DexRouter','AllowanceHolder','SwapRouter','SwapRouter02','MetaAggregationRouterV2','AggregationRouterV6'}
tr=[];te=[]; ops=tot=0
for k in rk:
    for t in r[k]['transactions']:
        tot+=1; ops+= t.get('method')=='handleOps'
        y=int((t.get('to') or '').lower() in Rn or t.get('to_name') in names)
        tip=(t.get('max_priority_fee_per_gas') or 0)/1e9
        (tr if int(k)<int(cut) else te).append(((glb(t['gas_limit']),int(math.log2(tip+1)*4)),y))
m=NB(2); m.fit([a for a,_ in tr],[b for _,b in tr]); report('2026 gas+tip',[m.score(a) for a,_ in te],[b for _,b in te])
print('handleOps share 2026',ops,tot,round(ops/tot,4))
