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
# Per-hop processing: a node validates (sig/gossipsub checks) before re-forwarding.
# This is the dominant reason real propagation is slower than raw link latency.
# Calibrated so PoS block reaches ~90% of nodes in a few hundred ms, matching
# measured Ethereum block propagation (Pioplat et al. 2023, ~150-200ms block
# reception on BSC; consensus-layer studies put p50 block arrival in the few-100ms
# range, well inside the 4 s attestation deadline).
PROC_S = 0.025      # 25 ms per-hop validation/processing delay


class Net:
    def __init__(self, n, seed, fanout=FANOUT):
        self.n = n
        self.rng = random.Random(seed)
        regions = list(REGION_WEIGHTS)
        weights = [REGION_WEIGHTS[r] for r in regions]
        self.region = [self.rng.choices(regions, weights)[0] for _ in range(n)]
        # random fanout graph (each node has >= fanout undirected peers)
        self.peers = [set() for _ in range(n)]
        for u in range(n):
            while len(self.peers[u]) < min(fanout, n - 1):
                v = self.rng.randrange(n)
                if v != u:
                    self.peers[u].add(v); self.peers[v].add(u)
        self.peers = [list(p) for p in self.peers]

    def one_way_s(self, u, v):
        base = lat_ms(self.region[u], self.region[v]) / 1000.0
        return base * (1 + self.rng.uniform(-JITTER, JITTER))

    def gossip(self, source, size_bytes):
        """Epidemic broadcast from source. Returns (recv_times, n_msgs, total_bytes).

        Models UPLINK CONGESTION: a node's outbound link is a single serial channel,
        so its `fanout` forwards QUEUE (the i-th peer's transmission finishes after
        (i+1) serializations), not blast out simultaneously. Under large blocks /
        high fanout this queueing is the dominant per-hop cost."""
        serial = size_bytes * 8 / BW_BPS
        recv = {source: 0.0}
        pq = [(0.0, source)]
        n_msgs = 0; total_bytes = 0
        while pq:
            t, u = heapq.heappop(pq)
            if t > recv[u]:
                continue  # stale (already had an earlier receipt)
            send_start = t + PROC_S                 # validate, then begin transmitting
            for i, v in enumerate(self.peers[u]):
                tx_done = send_start + (i + 1) * serial   # uplink serializes the fanout sends
                arr = tx_done + self.one_way_s(u, v)
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


def reveal_phase(net, K, mt_b=371):
    """MULTI-SOURCE MT reveal: K matching transactions are revealed by K different
    senders concurrently (not a single proposer gossip). Latency = single-MT
    propagation + the full-block ingest each validator must absorb; bandwidth = K
    concurrent gossips."""
    r, m_one, b_one = net.gossip(0, mt_b)        # one MT's epidemic propagation
    t_prop = net.pct(r, 0.90)
    t_ingest = serial_s(K * mt_b)                # each node receives all K MTs
    return t_prop + t_ingest, K * m_one, K * b_one


def agreement_all_to_all(net, K, ref_b=33):
    """NAIVE set-union: every validator gossips its full ref-set to everyone -> a
    node decides at 2f+1 sets. O(N^2) bandwidth -- the strawman bottleneck."""
    n = net.n; f = (n - 1) // 3; set_bytes = K * ref_b
    rA, mA_one, bA_one = net.gossip(0, set_bytes)
    t_prop = net.pct(rA, (2 * f + 1) / n if n else 1.0)
    return t_prop + (n * set_bytes) * 8 / BW_BPS, mA_one * n, bA_one * n


def agreement_aggregated(net, K, ref_b=33, leader=0):
    """LEADER collects N full ref-sets and unions them. O(N*K) leader ingest."""
    n = net.n; f = (n - 1) // 3; set_bytes = K * ref_b
    arrivals = sorted(net.one_way_s(v, leader) + serial_s(set_bytes) for v in range(n) if v != leader)
    collect = arrivals[min(len(arrivals) - 1, max(0, 2 * f - 1))] if arrivals else 0.0
    t_collect = max(collect, (n * set_bytes) * 8 / BW_BPS)
    rU, mU, bU = net.gossip(leader, K * ref_b)
    return t_collect + net.pct(rU, 0.90), (n - 1) + mU, n * set_bytes + bU


def agreement_bls(net, K, vote_b=112, qc_b=128, leader=0, byzantine=0):
    """REALISTIC P2S agreement (HotStuff-QC style): validators already hold the union
    from the reveal gossip, so they only VOTE on its 32-byte digest with a BLS
    signature. Leader collects 2f+1 votes (aggregatable to one QC) and gossips the
    QC. O(N) TINY messages; latency ~ one round-trip to the leader, N-cheap.

    byzantine: number of faulty validators that withhold their vote. Worst case
    (the adversary silences the fastest responders) is modeled by dropping the
    `byzantine` smallest arrivals, forcing the leader to wait for honest ones.
    With byzantine <= f the quorum of 2f+1 still forms (liveness)."""
    n = net.n; f = (n - 1) // 3
    arrivals = sorted(net.one_way_s(v, leader) + serial_s(vote_b) for v in range(n) if v != leader)
    arrivals = arrivals[byzantine:]              # adversary withholds the fastest votes
    collect = arrivals[min(len(arrivals) - 1, max(0, 2 * f - 1))] if arrivals else 0.0
    rQ, mQ, bQ = net.gossip(leader, qc_b)        # gossip the aggregated quorum cert
    return collect + net.pct(rQ, 0.90), (n - 1) + mQ, (n - 1) * vote_b + bQ


def byzantine_experiment(N_list=(50, 100, 250, 500, 1000), K=150, seeds=15):
    """Liveness + worst-case latency of the BLS agreement under up to f Byzantine
    validators that withhold votes (ties the network sim to the f<n/3 threat model)."""
    rows = []
    for n in N_list:
        f = (n - 1) // 3
        honest, byz = [], []
        for s in range(seeds):
            net = Net(n, seed=23 * s + n)
            honest.append(agreement_bls(net, K, byzantine=0)[0])
            byz.append(agreement_bls(net, K, byzantine=f)[0])   # max faults, worst case
        rows.append({"N": n, "f": f, "agree_honest_ms": _mean(honest) * 1000,
                     "agree_byz_ms": _mean(byz) * 1000})
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "netsim_byzantine.json")
    json.dump({"K": K, "seeds": seeds, "rows": rows}, open(path, "w"), indent=2)
    print("\n== agreement latency: honest vs worst-case f Byzantine (liveness holds) ==")
    for r in rows:
        print(f"  N={r['N']:>4} (f={r['f']:>3}): honest {r['agree_honest_ms']:5.0f}ms  "
              f"f-Byzantine {r['agree_byz_ms']:5.0f}ms")
    print(f"wrote {os.path.abspath(path)}")
    return rows


AGREEMENTS = {"bls": agreement_bls, "aggregated": agreement_aggregated, "all_to_all": agreement_all_to_all}


def p2s_slot(net, K, pht_b=77, mt_b=371, agreement="bls"):
    """P2S: B1 (proposer) -> multi-source MT reveal -> set-union agreement -> B2
    (proposer) -- sequential phases."""
    r1, m1, b1 = net.gossip(0, K * pht_b)        # B1: proposer gossips PHT order
    t_b1 = net.pct(r1, 0.90)
    t_reveal, m2, b2 = reveal_phase(net, K, mt_b)
    t_agr, mA, bA = AGREEMENTS[agreement](net, K)
    r4, m4, b4 = net.gossip(0, K * mt_b)         # B2: proposer gossips final block
    t_b2 = net.pct(r4, 0.90)
    return {
        "latency_s": t_b1 + t_reveal + t_agr + t_b2,
        "t_b1": t_b1, "t_reveal": t_reveal, "t_agreement": t_agr, "t_b2": t_b2,
        "msgs": m1 + m2 + mA + m4, "bytes": b1 + b2 + bA + b4, "agr_bytes": bA,
    }


def run(N_list=(10, 25, 50, 75, 100, 150, 250, 400, 600, 800, 1000), K=150, seeds=100):
    out = {"K": K, "seeds": seeds, "fanout": FANOUT, "bw_mbps": BW_BPS / 1e6, "rows": []}
    print(f"network-env simulation: K={K} txs/block, {seeds} seeds, GossipSub D={FANOUT}, {BW_BPS/1e6:.0f} Mbps")
    print(f"{'N':>5} {'PoS lat':>9} {'P2S lat':>9} {'overhead':>9} {'agree(bls)':>11} "
          f"{'PoS MB':>8} {'P2S MB':>8} {'agrMB:bls/agg/naive':>22}")
    for n in N_list:
        acc = {k: [] for k in ("pos_l", "pos_mb", "p2s_l", "agr", "p2s_mb",
                                "b1", "rev", "b2", "agr_bls", "agr_agg", "agr_naive")}
        for s in range(seeds):
            net = Net(n, seed=1000 * s + n)
            p = pos_slot(net, K)
            q = p2s_slot(net, K, agreement="bls")
            _, _, b_agg = agreement_aggregated(net, K)
            _, _, b_naive = agreement_all_to_all(net, K)
            acc["pos_l"].append(p["latency_s"]); acc["pos_mb"].append(p["bytes"] / 1e6)
            acc["p2s_l"].append(q["latency_s"]); acc["p2s_mb"].append(q["bytes"] / 1e6)
            acc["agr"].append(q["t_agreement"])
            acc["b1"].append(q["t_b1"]); acc["rev"].append(q["t_reveal"]); acc["b2"].append(q["t_b2"])
            acc["agr_bls"].append(q["agr_bytes"] / 1e6)
            acc["agr_agg"].append(b_agg / 1e6); acc["agr_naive"].append(b_naive / 1e6)

        def ci(xs):
            m = st.mean(xs)
            return m, (1.96 * st.pstdev(xs) / math.sqrt(len(xs)) if len(xs) > 1 else 0.0)
        pos_m, pos_h = ci(acc["pos_l"]); p2s_m, p2s_h = ci(acc["p2s_l"]); agr_m, _ = ci(acc["agr"])
        row = {"N": n, "pos_lat_s": pos_m, "pos_ci": pos_h, "p2s_lat_s": p2s_m, "p2s_ci": p2s_h,
               "overhead_s": p2s_m - pos_m, "agreement_s": agr_m,
               "t_b1_s": st.mean(acc["b1"]), "t_reveal_s": st.mean(acc["rev"]), "t_b2_s": st.mean(acc["b2"]),
               "pos_mb_per_slot": st.mean(acc["pos_mb"]), "p2s_mb_per_slot": st.mean(acc["p2s_mb"]),
               "agr_mb_bls": st.mean(acc["agr_bls"]), "agr_mb_aggregated": st.mean(acc["agr_agg"]),
               "agr_mb_naive": st.mean(acc["agr_naive"]), "slot_budget_frac": p2s_m / 12.0}
        out["rows"].append(row)
        print(f"{n:>5} {pos_m*1000:>7.1f}ms {p2s_m*1000:>7.1f}ms {(p2s_m-pos_m)*1000:>7.1f}ms "
              f"{agr_m*1000:>9.1f}ms {st.mean(acc['pos_mb']):>6.1f}MB {st.mean(acc['p2s_mb']):>6.1f}MB "
              f"{st.mean(acc['agr_bls']):>6.2f}/{st.mean(acc['agr_agg']):>6.1f}/{st.mean(acc['agr_naive']):>7.1f}")
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "netsim_results.json")
    json.dump(out, open(path, "w"), indent=2)
    print(f"\nwrote {os.path.abspath(path)}")
    return out


def _mean(xs):
    return st.mean(xs) if xs else 0.0


def _ci(xs):
    """95% confidence half-width of the mean (1.96 * SEM)."""
    return 1.96 * st.pstdev(xs) / math.sqrt(len(xs)) if len(xs) > 1 else 0.0


def sweep_K(N=500, Ks=(50, 100, 150, 250, 400, 600, 800, 1000), seeds=100):
    """Robustness to block size K (txs/slot) at fixed committee N."""
    rows = []
    for K in Ks:
        pos_l, p2s_l, pos_mb, p2s_mb = [], [], [], []
        for s in range(seeds):
            net = Net(N, seed=7 * s + K)
            p = pos_slot(net, K); q = p2s_slot(net, K, agreement="bls")
            pos_l.append(p["latency_s"]); p2s_l.append(q["latency_s"])
            pos_mb.append(p["bytes"] / 1e6); p2s_mb.append(q["bytes"] / 1e6)
        rows.append({"K": K, "pos_lat_s": _mean(pos_l), "p2s_lat_s": _mean(p2s_l),
                     "pos_ci": _ci(pos_l), "p2s_ci": _ci(p2s_l),
                     "pos_mb": _mean(pos_mb), "p2s_mb": _mean(p2s_mb)})
    return rows


def sweep_fanout(N=500, K=150, Ds=(4, 6, 8, 12, 16, 24, 32), seeds=100):
    """Robustness to GossipSub mesh degree D at fixed N, K."""
    rows = []
    for D in Ds:
        pos_l, p2s_l = [], []
        for s in range(seeds):
            net = Net(N, seed=11 * s + D, fanout=D)
            pos_l.append(pos_slot(net, K)["latency_s"])
            p2s_l.append(p2s_slot(net, K, agreement="bls")["latency_s"])
        rows.append({"fanout": D, "pos_lat_s": _mean(pos_l), "p2s_lat_s": _mean(p2s_l),
                     "pos_ci": _ci(pos_l), "p2s_ci": _ci(p2s_l)})
    return rows


def sweeps():
    out = {"K_sweep_N": 500, "fanout_sweep_N": 500,
           "K_sweep": sweep_K(), "fanout_sweep": sweep_fanout()}
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "netsim_sweeps.json")
    json.dump(out, open(path, "w"), indent=2)
    print("\n== K sweep (N=500) ==")
    for r in out["K_sweep"]:
        print(f"  K={r['K']:>4}: PoS {r['pos_lat_s']*1000:6.0f}ms  P2S {r['p2s_lat_s']*1000:6.0f}ms  "
              f"P2S {r['p2s_mb']:6.1f}MB")
    print("== fanout sweep (N=500, K=150) ==")
    for r in out["fanout_sweep"]:
        print(f"  D={r['fanout']:>2}: PoS {r['pos_lat_s']*1000:6.0f}ms  P2S {r['p2s_lat_s']*1000:6.0f}ms")
    print(f"wrote {os.path.abspath(path)}")
    return out


if __name__ == "__main__":
    run()
    sweeps()
    byzantine_experiment()
