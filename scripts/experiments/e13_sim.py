"""E13 EVM engine: sandwich simulation on a local anvil fork of mainnet, for Uniswap V2, V3, V4.

All three transactions of a sandwich (front leg, victim, back leg) are mined in ONE block at the
victim block's real timestamp, on top of the pre-block state (fork at n-1), in that order. This is
the proposer's best placement: it controls the order of S1, so it puts the bracket first.
Fees are zeroed inside the fork; the economics (F_res, gas) are added afterwards in Python."""
import json, os, subprocess, time, urllib.request

ROOT = '/Users/tammy/Code/P2S'
FORK_RPC = os.environ.get('P2S_ARCHIVE_RPC') or 'https://eth.drpc.org'   # same chain data; archive RPC is faster
PM = '0x000000000004444c5dc75cb358380d2e3de08a90'          # Uniswap V4 PoolManager
V4_INIT = '0xdd466e674ea557f56295e2d0218a125ea4b4f0f6f3307b95f85e6110838d6438'
V4_DEPLOY = 21688329
WETH = '0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2'
USDC = '0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48'
USDT = '0xdac17f958d2ee523a2206206994597c13d831ec7'
DAI = '0x6b175474e89094c44da98b954eedeac495271d0f'
STABLE = {USDC: 6, USDT: 6, DAI: 18}
REF_POOL = '0x88e6a0c2ddd26feeb64f039a2c41296fcb3f5640'      # V3 USDC/WETH 0.05%, ETH/USD reference
EOA = '0x00000000000000000000000000000000000a77ac'          # attacker EOA (auto-impersonated)
ART = json.load(open(f'{ROOT}/real/sim13/out/Legs.sol/Legs.json'))
BYTECODE = ART['bytecode']['object']
SEL = {'v2': '0x' + subprocess.run(['cast', 'sig', 'v2(address,bool,uint256)'], capture_output=True, text=True).stdout.strip()[2:],
       'v3': '0x' + subprocess.run(['cast', 'sig', 'v3(address,bool,uint256)'], capture_output=True, text=True).stdout.strip()[2:],
       'v4': '0x' + subprocess.run(['cast', 'sig', 'v4((address,address,uint24,int24,address),bool,uint256)'], capture_output=True, text=True).stdout.strip()[2:]}
V4KEY_CACHE = f'{ROOT}/data/experiments/_e13/v4keys.json'


def h32(x):
    return hex(x)[2:].rjust(64, '0')


def addr32(a):
    return a.lower()[2:].rjust(64, '0')


def i32(x):
    return h32(x % (1 << 256))


_SLOT = {}


def reserve_slot(token):
    if token not in _SLOT:
        _SLOT[token] = subprocess.run(['cast', 'index', 'address', token, '0'], capture_output=True,
                                      text=True).stdout.strip()
    return _SLOT[token]


def remote(method, params):
    from e7_labels import rpc
    return rpc(method, params)


TOPIC = {2: '0xd78ad95fa46c994b6551d0da85fc275fe613ce37657fb8d5e3d130840159d822',
         3: '0xc42079f94a6350d7e6235f29174924f928cc2ac818eb64fed8004e115fbcca67',
         4: '0x40e9cecb9f5f1f1c5b9c97dec2917b7ee92e57ba5563708daca94dd84ad7112f'}


def _sw(x):
    return x - (1 << 256) if x >= 1 << 255 else x


def swap_in(logs, pool, ver, z):
    """Input amount of the first Swap log on `pool` (V4: pool id) in direction z."""
    for l in logs:
        if not l['topics'] or l['topics'][0] != TOPIC[ver]:
            continue
        if ver == 4 and l['topics'][1] != pool:
            continue
        if ver != 4 and l['address'].lower() != pool:
            continue
        d = l['data'][2:]
        w = lambda i: int(d[64 * i:64 * (i + 1)], 16)
        if ver == 2:
            return w(0) if z else w(1)
        if ver == 3:
            return _sw(w(0)) if z else _sw(w(1))
        return -_sw(w(0)) if z else -_sw(w(1))
    return None


class V4Keys:
    def __init__(s):
        s.k = json.load(open(V4KEY_CACHE)) if os.path.exists(V4KEY_CACHE) else {}

    def get(s, pid):
        if pid not in s.k:
            u = ('https://eth.blockscout.com/api?module=logs&action=getLogs&address=' + PM + '&topic0=' + V4_INIT +
                 '&topic1=' + pid + '&topic0_1_opr=and&fromBlock=' + str(V4_DEPLOY) + '&toBlock=latest')
            L = None
            for t in range(8):
                try:
                    L = json.loads(subprocess.run(['curl', '-s', '--fail', '-m', '60', u], capture_output=True,
                                                  timeout=90, check=True).stdout)['result']
                    break
                except Exception:
                    time.sleep(2 + 2 * t)
            if not L:
                s.k[pid] = None
            else:
                l = L[0]
                d = l['data'][2:]
                fee = int(d[0:64], 16)
                ts = int(d[64:128], 16)
                ts = ts - (1 << 256) if ts >= 1 << 255 else ts
                hooks = '0x' + d[128 + 24:192]
                s.k[pid] = ['0x' + l['topics'][2][-40:], '0x' + l['topics'][3][-40:], fee, ts, hooks]
            json.dump(s.k, open(V4KEY_CACHE, 'w'))
        return s.k[pid]


class Anvil:
    def __init__(s, port, block):
        # always take a fresh free port: a stale anvil left on a fixed port would answer instead
        # of the new fork and carry an advanced chain (timestamp errors)
        import socket
        with socket.socket() as so:
            so.bind(('127.0.0.1', 0))
            port = so.getsockname()[1]
        s.port = port
        s.url = f'http://127.0.0.1:{port}'
        s.p = subprocess.Popen(['anvil', '--fork-url', FORK_RPC, '--fork-block-number', str(block), '--port', str(port),
                                '--auto-impersonate', '--order', 'fifo', '--silent', '--base-fee', '0',
                                '--compute-units-per-second', '330', '--retries', '10', '--timeout', '60000'],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(480):
            try:
                s.call('eth_blockNumber', [])
                break
            except Exception:
                time.sleep(0.5)
        assert int(s.call('eth_blockNumber', []), 16) == block, 'anvil is not at the fork block'
        s.block = block
        s.legs = {}
        s.tok = {}
        s.funded = set()
        s.px = {}
        s.next_ts = int(s.call('eth_getBlockByNumber', ['latest', False])['timestamp'], 16) + 1

    def call(s, m, p):
        req = urllib.request.Request(s.url, json.dumps(dict(jsonrpc='2.0', id=1, method=m, params=p)).encode(),
                                     {'content-type': 'application/json'})
        r = json.loads(urllib.request.urlopen(req, timeout=600).read())
        if 'error' in r:
            raise RuntimeError(r['error'])
        return r['result']

    def close(s):
        s.p.terminate()
        try:
            s.p.wait(20)
        except Exception:
            s.p.kill()

    def reset(s, block):
        s.call('anvil_reset', [dict(forking=dict(jsonRpcUrl=FORK_RPC, blockNumber=block))])
        assert int(s.call('eth_blockNumber', []), 16) == block, 'anvil is not at the fork block'
        s.block = block
        s.legs = {}

    # ------------------------------------------------------------------ basics
    def eth_call(s, to, data, frm=EOA):
        return s.call('eth_call', [dict(**{'from': frm, 'to': to, 'data': data}), 'latest'])

    def balance(s, token, who):
        if token == '0x0000000000000000000000000000000000000000':
            return int(s.call('eth_getBalance', [who, 'latest']), 16)
        r = s.eth_call(token, '0x70a08231' + addr32(who))
        return int(r, 16) if r and r != '0x' else 0

    def tokens(s, pool, ver):
        if ver == 4:
            return None
        if pool not in s.tok:
            s.tok[pool] = ('0x' + s.eth_call(pool, '0x0dfe1681')[-40:], '0x' + s.eth_call(pool, '0xd21220a7')[-40:])
        return s.tok[pool]

    def send(s, frm, to, data, value=0, gas=3_000_000):
        return s.call('eth_sendTransaction', [{'from': frm, 'to': to, 'data': data, 'value': hex(value),
                                               'gas': hex(gas), 'gasPrice': '0x0'}])

    def deploy(s, name):
        if name in s.legs:
            return s.legs[name]
        s.call('anvil_setBalance', [EOA, hex(10 ** 24)])
        s.call('evm_setAutomine', [True])
        s.call('anvil_setNextBlockBaseFeePerGas', ['0x0'])
        last = int(s.call('eth_getBlockByNumber', ['latest', False])['timestamp'], 16)
        s.next_ts = max(s.next_ts, last + 1)
        s.call('anvil_setNextBlockTimestamp', [hex(s.next_ts)])     # keep helper blocks before the victim block
        s.next_ts += 1
        h = s.send(EOA, None, BYTECODE + addr32(PM), gas=5_000_000)
        r = s.call('eth_getTransactionReceipt', [h])
        if r is None:
            s.call('evm_mine', [])
            r = s.call('eth_getTransactionReceipt', [h])
        s.legs[name] = r['contractAddress'].lower()
        return s.legs[name]

    BIG = 10 ** 33

    def fund(s, token, who, amount=None):
        """Give helper `who` a large balance of `token` once, and mark it as reserve."""
        if (who, token) in s.funded:
            return
        if token == '0x0000000000000000000000000000000000000000':
            s.call('anvil_setBalance', [who, hex(s.BIG)])
        else:
            s.call('anvil_dealERC20', [who, token, hex(s.BIG)])
        bal = s.balance(token, who)
        # reserve[token] lives in mapping slot 0; write it directly so no block is mined
        s.call('anvil_setStorageAt', [who, reserve_slot(token), '0x' + h32(bal)])
        s.funded.add((who, token))

    # ------------------------------------------------------------------ legs
    def leg_data(s, pool, ver, key, z, amt):
        if ver == 2:
            return SEL['v2'] + addr32(pool) + h32(int(z)) + h32(amt)
        if ver == 3:
            return SEL['v3'] + addr32(pool) + h32(int(z)) + h32(amt)
        return SEL['v4'] + addr32(key[0]) + addr32(key[1]) + h32(key[2]) + i32(key[3]) + addr32(key[4]) + h32(int(z)) + h32(amt)

    def io(s, pool, ver, key, z):
        t0, t1 = (key[0], key[1]) if ver == 4 else s.tokens(pool, ver)
        return (t0, t1) if z else (t1, t0)

    def quote(s, pool, ver, key, z, amt, who):
        """Output of a single exact-input swap at the current state, without committing it."""
        tin, _ = s.io(pool, ver, key, z)
        s.fund(tin, who)
        r = s.eth_call(who, s.leg_data(pool, ver, key, z, amt))
        return int(r, 16) if r and r != '0x' else 0

    # ------------------------------------------------------------------ sandwich in one block
    def sandwich(s, pool, ver, key, z, front, victim, ts):
        """victim = ('real', tx dict) or ('synthetic', amount). Returns dict with the attacker's
        profit in the input token, victim output, victim status. State is reverted afterwards."""
        A = s.deploy('attacker')
        Vs = s.deploy('victim') if victim[0] == 'synthetic' else None
        tin, tout = s.io(pool, ver, key, z)
        s.fund(tin, A)
        if Vs:
            s.fund(tin, Vs)
        snap = s.call('evm_snapshot', [])
        try:
            a0 = s.balance(tin, A)
            v0 = s.balance(tout, Vs) if Vs else None
            s.call('evm_setAutomine', [False])
            hs = []
            if front:
                hs.append(s.send(EOA, A, s.leg_data(pool, ver, key, z, front)))
            if victim[0] == 'real':
                t = victim[1]
                hs.append(s.send(t['s'], t['to'], t['input'], t['value'], max(t['gas'], 300_000)))
            else:
                hs.append(s.send(EOA, Vs, s.leg_data(pool, ver, key, z, victim[1])))
            if front:
                hs.append(s.send(EOA, A, s.leg_data(pool, ver, key, not z, 0)))
            s.call('anvil_setNextBlockBaseFeePerGas', ['0x0'])
            if ts:
                # anvil may already sit at or past the victim's timestamp (helper blocks); then mine
                # one second later. Never triggered on the 2026 window, so those results are unchanged.
                last = int(s.call('eth_getBlockByNumber', ['latest', False])['timestamp'], 16)
                ts_ = ts if ts > last else last + 1
                s.ts_bumped = getattr(s, 'ts_bumped', 0) + (ts_ != ts)
            s.call('evm_mine', [{'timestamp': ts_}] if ts else [])
            rc = [s.call('eth_getTransactionReceipt', [h]) for h in hs]
            st = [int(r['status'], 16) if r else -1 for r in rc]
            vic_out = (s.balance(tout, Vs) - v0) if Vs else None
            vic_in = None
            if victim[0] == 'real' and rc[len(hs) - 2 if front else 0]:
                vic_in = swap_in(rc[len(hs) - 2 if front else 0]['logs'], pool, ver, z)
            end = s.balance(tin, A) if front else a0
            return dict(profit_in=end - a0, status=st, victim_out=vic_out, victim_in=vic_in,
                        gas=[int(r['gasUsed'], 16) if r else 0 for r in rc])
        finally:
            s.call('evm_revert', [snap])
            s.call('evm_setAutomine', [True])

    # ------------------------------------------------------------------ value in ETH
    def to_eth(s, token, amount, pool, ver, key, z):
        """Value `amount` of `token` in ETH at the pre-block price, by a small probe swap."""
        if amount == 0:
            return 0.0
        if token in (WETH, '0x0000000000000000000000000000000000000000'):
            return amount / 1e18
        sign = 1 if amount > 0 else -1
        amt = abs(amount)
        t0, t1 = (key[0], key[1]) if ver == 4 else s.tokens(pool, ver)
        other = t1 if token == t0 else t0
        if token not in s.px:
            s.px[token] = None
            if other in (WETH, '0x0000000000000000000000000000000000000000'):
                probe = max(amt // 1000, 1)
                out = s.quote(pool, ver, key, token == t0, probe, s.deploy('probe'))
                s.px[token] = out / probe / 1e18 if out else None          # ETH per token unit
            elif token in STABLE:
                probe = 10 ** 15
                out = s.quote(REF_POOL, 3, None, False, probe, s.deploy('probe'))   # WETH -> USDC
                if out:
                    s.px[token] = (probe / 1e18) / (out / 1e6) / 10 ** STABLE[token]
        return sign * amt * s.px[token] if s.px[token] is not None else None
