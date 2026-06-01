#!/usr/bin/env python3
"""Discrete-event NETWORK-ENVIRONMENT simulation of P2S vs Ethereum PoS.

Unlike the legacy scalar-delay model (simulator.py: base 0.1 + uniform jitter),
this models the actual distributed system: N validator nodes placed across
geographic regions with a calibrated one-way latency matrix, connected in a
random fanout graph, with GossipSub-style epidemic message propagation. We
simulate the real per-slot message flow:

  PoS  : proposer gossips the block            -> 1 propagation
  P2S  : B1 gossip -> MT-reveal gossip -> set-union AGREEMENT (all-to-all, with
         the N-set ingest bottleneck) -> B2 gossip   -> 4 sequential phases

and measure per-phase / total latency, message count, and bandwidth, as a
function of committee size N, with seeds + confidence intervals.

Calibration (cited in-line): inter-region one-way latencies ~ cloud RTT/2
(AWS/cloudping inter-region medians); validator geographic distribution from
ethernodes/Miga Labs (~US 45% / EU 35% / Asia 15% / other 5%); GossipSub mesh
degree D=8 (Ethereum consensus p2p spec); validator link 50 Mbps.
"""
import heapq, json, os, random, statistics as st, math

# --- one-way latency matrix between regions (milliseconds); ~ cloud RTT/2 ---
REGIONS = ["NA_E", "NA_W", "EU", "ASIA", "OCE_SA"]
LAT_MS = {  # symmetric one-way ms
    ("NA_E", "NA_E"): 4,  ("NA_W", "NA_W"): 4,  ("EU", "EU"): 4,
    ("ASIA", "ASIA"): 6,  ("OCE_SA", "OCE_SA"): 8,
    ("NA_E", "NA_W"): 30, ("NA_E", "EU"): 40, ("NA_E", "ASIA"): 95, ("NA_E", "OCE_SA"): 75,
    ("NA_W", "EU"): 65,   ("NA_W", "ASIA"): 70, ("NA_W", "OCE_SA"): 70,
    ("EU", "ASIA"): 85,   ("EU", "OCE_SA"): 110,
    ("ASIA", "OCE_SA"): 90,
}
def lat_ms(a, b):
    return LAT_MS.get((a, b)) or LAT_MS.get((b, a)) or 50
# realistic validator geographic distribution (ethernodes / Miga Labs)
REGION_WEIGHTS = {"NA_E": 0.30, "NA_W": 0.15, "EU": 0.35, "ASIA": 0.15, "OCE_SA": 0.05}

FANOUT = 8          # GossipSub mesh degree D (Ethereum consensus p2p)
BW_BPS = 50e6       # 50 Mbps validator link
JITTER = 0.15       # +/-15% link-latency jitter


class Net:
    def __init__(self, n, seed):
        self.n = n
        self.rng = random.Random(seed)
        regions = list(REGION_WEIGHTS)
        weights = [REGION_WEIGHTS[r] for r in regions]
        self.region = [self.rng.choices(regions, weights)[0] for _ in range(n)]
        # random fanout graph (each node has >= FANOUT undirected peers)
        self.peers = [set() for _ in range(n)]
        for u in range(n):
            while len(self.peers[u]) < min(FANOUT, n - 1):
                v = self.rng.randrange(n)
                if v != u:
                    self.peers[u].add(v); self.peers[v].add(u)
        self.peers = [list(p) for p in self.peers]

    def one_way_s(self, u, v):
        base = lat_ms(self.region[u], self.region[v]) / 1000.0
        return base * (1 + self.rng.uniform(-JITTER, JITTER))

    def gossip(self, source, size_bytes):
        """Epidemic broadcast from source. Returns (recv_times, n_msgs, total_bytes)."""
        serial = size_bytes * 8 / BW_BPS
        recv = {source: 0.0}
        pq = [(0.0, source)]
        n_msgs = 0; total_bytes = 0
        while pq:
            t, u = heapq.heappop(pq)
            if t > recv[u]:
                continue  # stale (already had an earlier receipt)
            for v in self.peers[u]:
                arr = t + serial + self.one_way_s(u, v)
                n_msgs += 1; total_bytes += size_bytes
                if v not in recv or arr < recv[v]:
                    recv[v] = arr
                    heapq.heappush(pq, (arr, v))
        return recv, n_msgs, total_bytes

    @staticmethod
    def pct(recv, q):
        xs = sorted(recv.values())
        return xs[min(len(xs) - 1, int(q * len(xs)))]


def serial_s(size_bytes):
    return size_bytes * 8 / BW_BPS


def pos_slot(net, K, tx_bytes=374):
    """PoS: proposer gossips one block of K txs; latency = time to 90% delivery."""
    block = K * tx_bytes
    recv, msgs, byts = net.gossip(0, block)
    return {"latency_s": net.pct(recv, 0.90), "msgs": msgs, "bytes": byts}


def agreement_all_to_all(net, K, ref_b=33):
    """NAIVE set-union: every validator gossips its full ref-set to everyone. A node
    decides at 2f+1 sets. O(N^2) bandwidth (gossip x N sources) -- the bottleneck."""
    n = net.n; f = (n - 1) // 3; set_bytes = K * ref_b
    rA, mA_one, bA_one = net.gossip(0, set_bytes)
    t_prop = net.pct(rA, (2 * f + 1) / n if n else 1.0)
    t_ingest = (n * set_bytes) * 8 / BW_BPS
    return t_prop + t_ingest, mA_one * n, bA_one * n


def agreement_aggregated(net, K, ref_b=33, leader=0):
    """LEADER-AGGREGATED set-union (realistic BFT, HotStuff-style): each validator
    sends its ref-set directly to the leader; leader unions and gossips the result.
    O(N) bandwidth. Latency = collect 2f+1 (bounded by leader ingest) + gossip union."""
    n = net.n; f = (n - 1) // 3; set_bytes = K * ref_b
    arrivals = sorted(net.one_way_s(v, leader) + serial_s(set_bytes) for v in range(n) if v != leader)
    collect = arrivals[min(len(arrivals) - 1, max(0, 2 * f - 1))] if arrivals else 0.0
    ingest = (n * set_bytes) * 8 / BW_BPS          # leader must receive N sets
    t_collect = max(collect, ingest)
    rU, mU, bU = net.gossip(leader, K * ref_b)     # gossip the (deduped) union
    t_gossip = net.pct(rU, 0.90)
    return t_collect + t_gossip, (n - 1) + mU, n * set_bytes + bU


def p2s_slot(net, K, pht_b=77, mt_b=371, ref_b=33, agreement="aggregated"):
    """P2S: B1 -> MT reveal -> set-union agreement -> B2 (sequential phases)."""
    r1, m1, b1 = net.gossip(0, K * pht_b)
    t_b1 = net.pct(r1, 0.90)
    r2, m2, b2 = net.gossip(0, K * mt_b)
    t_reveal = net.pct(r2, 0.90)
    agr_fn = agreement_aggregated if agreement == "aggregated" else agreement_all_to_all
    t_agreement, msgs_A, bytes_A = agr_fn(net, K, ref_b)
    r4, m4, b4 = net.gossip(0, K * mt_b)
    t_b2 = net.pct(r4, 0.90)
    total = t_b1 + t_reveal + t_agreement + t_b2
    return {
        "latency_s": total, "t_b1": t_b1, "t_reveal": t_reveal,
        "t_agreement": t_agreement, "t_b2": t_b2,
        "msgs": m1 + m2 + msgs_A + m4, "bytes": b1 + b2 + bytes_A + b4,
    }


def run(N_list=(10, 50, 100, 250, 500, 1000), K=150, seeds=20):
    out = {"K": K, "seeds": seeds, "fanout": FANOUT, "bw_mbps": BW_BPS / 1e6, "rows": []}
    print(f"network-env simulation: K={K} txs/block, {seeds} seeds, GossipSub D={FANOUT}, {BW_BPS/1e6:.0f} Mbps")
    print(f"{'N':>5} {'PoS lat':>10} {'P2S lat':>10} {'overhead':>10} {'agree(agg)':>11} {'P2S MB(agg)':>12} {'MB(naive)':>11}")
    for n in N_list:
        pos_l, p2s_l, agr, p2s_mb, naive_mb, p2s_b1, p2s_rev, p2s_b2 = [], [], [], [], [], [], [], []
        for s in range(seeds):
            net = Net(n, seed=1000 * s + n)
            p = pos_slot(net, K)
            q = p2s_slot(net, K, agreement="aggregated")
            _, _, nb = agreement_all_to_all(net, K)
            pos_l.append(p["latency_s"]); p2s_l.append(q["latency_s"])
            agr.append(q["t_agreement"]); p2s_mb.append(q["bytes"] / 1e6); naive_mb.append(nb / 1e6)
            p2s_b1.append(q["t_b1"]); p2s_rev.append(q["t_reveal"]); p2s_b2.append(q["t_b2"])

        def ci(xs):
            m = st.mean(xs)
            h = 1.96 * (st.pstdev(xs) / math.sqrt(len(xs))) if len(xs) > 1 else 0.0
            return m, h
        pos_m, pos_h = ci(pos_l); p2s_m, p2s_h = ci(p2s_l); agr_m, _ = ci(agr); mb_m, _ = ci(p2s_mb)
        row = {"N": n, "pos_lat_s": pos_m, "pos_ci": pos_h, "p2s_lat_s": p2s_m, "p2s_ci": p2s_h,
               "overhead_s": p2s_m - pos_m, "agreement_s": agr_m,
               "t_b1_s": st.mean(p2s_b1), "t_reveal_s": st.mean(p2s_rev), "t_b2_s": st.mean(p2s_b2),
               "p2s_mb_per_slot": mb_m, "naive_mb_per_slot": st.mean(naive_mb),
               "slot_budget_frac": p2s_m / 12.0}
        out["rows"].append(row)
        print(f"{n:>5} {pos_m*1000:>8.1f}ms {p2s_m*1000:>8.1f}ms {(p2s_m-pos_m)*1000:>8.1f}ms "
              f"{agr_m*1000:>9.1f}ms {mb_m:>10.2f}MB {st.mean(naive_mb):>9.1f}MB")
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "netsim_results.json")
    json.dump(out, open(path, "w"), indent=2)
    print(f"\nwrote {os.path.abspath(path)}")
    return out


if __name__ == "__main__":
    run()
