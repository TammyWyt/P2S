# P2S — Hardened Simulation + Threat-Model Spec

Source: deep-research workflow (BlindPerm IACR 2023/1061 + Qin et al. S&P'22 + PROF + F3B + Eating Sandwiches), with two hostile-reviewer critiques applied. The reviews verified our on-disk data and found two FATAL flaws; this spec adopts their fixes.

## HEADLINE REFRAME (non-negotiable)
Do NOT claim "0.878 → -0.138 ETH inversion" or "P2S MEV is negative."
- The −0.137 "P2S MEV" is just the **gas cost of an irrational attacker submitting useless legs** — true of any protocol. A *rational* attacker submits nothing → nets **0**.
- The +0.878 number is from **100-ETH synthetic victims that do not occur in our real workload** (real victims ≤ 4.96 ETH, below the t8n profitability threshold → measured MEV ≈ 0, reduction = NaN).
- Honest claim (G2, Angeris et al.): **P2S removes the positive expected value of in-slot content-dependent MEV, driving the rational attacker's payoff to the blind-ordering baseline (~0).** Anchor every number to G2, never to zero.

## THREAT MODEL (hardened)
- System: standing PoS validator set, n parties, f<n/3 Byzantine, PPT adversary. B1 commits order π (c_i=H(m_i,r_i)); B2 reveals via set-union agreement; execute m_i in order π. Property: order committed before THIRD-PARTY content is revealed (P2S is NOT a confidentiality protocol — B2 is plaintext).
- Network: authenticated channels (PKI); partial synchrony (DLS GST); n≥3f+1; ROM commitment binding+hiding (load-bearing).
- Adversary classes & sim obligations:
  - A1 malicious proposer (grind B1 layout) → show no 3rd-party advantage; report conceded self-MEV residual.
  - A2 external searcher → t8n on REAL attacked trades (primary validation).
  - **A2-meta (NEW): position on B1-visible metadata (gasLimit bucket, slot count, timing).** → measure residual win-rate; see amendment 1.
  - A3 colluding committee (≤f): reveal-equivocation / non-reveal → burn not reorder; measure burn/stall vs f.
  - A4 cross-slot: backrun public post-exec state across slots → OUT of scope but NET-SIGN-TESTED (rule out that B1/B2 split increases cross-slot surface).
  - A5 rushing/adaptive → no adaptive-security claim.
- Security goals: G1 content-ordering independence (scoped to content AND B1-metadata, see amend.1); G2 MEV ≤ blind-ordering baseline; G3 F_res deters spam/speculation ONLY (not value-exceeding targeted censorship); G4 ordering-safety unconditional + abandon-and-compact.

### PROTOCOL AMENDMENTS surfaced by the critique (must implement/decide)
1. **Gas metadata — RESOLVED (author decision, 2026-06-01, no seal needed).** By design the PHT discloses only `gasLimit`, `maxFeePerGas`, and `priorityFee` (the fields needed to order by priority fee and charge `F_res`); recipient/value/calldata stay hidden. `gasLimit` is an UPPER BOUND (a limit, not actual gas used); true gas consumed and final cost are confirmed only after B2 settles. This metadata reveals coarse tx-TYPE but NOT which pool / direction / size a victim trades — so a metadata-only attacker cannot construct a targeted sandwich and DEGENERATES to blind-planting. VALIDATED (`real/data/metadata_residual.json`, A2-meta): with a generous guessing space (175 active pools, ~18/block) E[gross]≈5.5e-5 ETH vs cost 0.0042 ETH (2 legs gas + F_res) ⇒ E[profit] = −0.0041 ETH < 0 ⇒ residual metadata MEV = 0. G1 stands as "order independent of content; disclosed fee-metadata is insufficient for content-dependent positioning."
2. **Abandon-and-compact, not abandon-and-burn.** A burned slot's content is dropped but opened slots compact preserving committed relative order → a burn is a no-op (no permanent hole / throughput-DoS griefing).
3. **Threshold-BLS unbiasable seed (optional).** To claim "≤ uniformly-random ordering" we need an unbiasable seed over the B1-committed set; otherwise only the weaker **adversarial-blind worst-case** baseline is honest.

## SIMULATION DESIGN (hardened) — 5 gating fixes
1. **Regime mismatch (FATAL):** t8n profitable only for victims ≥~15 ETH, but real fixtures ≤4.96 ETH → all zeros/NaN. FIX: regenerate the t8n anchor on the **ACTUAL attacked trades** (re-extract the 60 detected sandwiches' victim sizes), not random sub-5-ETH swaps.
2. **Gas-floor artifact (FATAL):** model the **attacker participation constraint** `net = max(0, E[blind] − legs − F_res)`; rational P2S net → 0, not −0.137.
3. **Single-snapshot / heavy tail:** top-3 = 78% → wide BCa CIs (show them); multiple windows; derive κ from t8n (not imported 0.63); NegBinom (not Poisson) counts.
4. **Random arm mis-specified:** reproduce BlindPerm `Pr[win]=1−|i−j|/|B|` verbatim, joint front+back, |B| from the same blocks.
5. **Latency single-host artifact:** 97→482ms N=64 cliff is O(N²) single-host, not WAN. FIX: WAN-emulate (Shadow/ns-3/geo, calibrate to Ethereum p50~250ms/p99~1s) OR downgrade to "local lower bound" + explain.

Architecture: L1 calibration (real data → frozen, SHA-256-hashed, source-tagged distributions) · L2 four-arm MC core (Historical / PoS / Random / P2S) · L3 validation (t8n on real attacked trades + GoF vs 60 real attacks + cross-estimator). Every distribution tagged `calibrated|assumed`.

## CALIBRATION TABLE (hard-code; value / source)
- Per-attack MEV v: bootstrap of all_profits_eth (n=60; median 6.15e-4, max 0.724, top-3=78%) — sandwiches.json
- κ capture efficiency: DERIVE from t8n (0.63 Qin S&P'22 as cross-check only)
- Attacks/block: NegBinom rate 0.15 (swept 0.15–0.3) — Qin'22/Yang'24/Heimbach'22
- Victim trade size: RE-EXTRACT from the 60 attacked trades (not random swaps)
- Pool reserves: USDC/WETH 4536.6, WETH/USDT 3803.3, DAI/WETH 2085.6 ETH @ blk 25221314
- Pool depth: sweep 2000–4500 ETH (first-class axis)
- Victim slippage tol.: mode 0.5%, clusters 1/5/10%, cap 50% — Chemaya FC'24
- Block size |B|: from the same blocks the attacks came from (not BlindPerm's 231)
- Base fee: 7–30 gwei (spikes 100–500); φ swept 0.01–1.0
- Latency/bandwidth: latency.json / bandwidth.json (WAN-calibrate or downgrade)
Citations: BlindPerm 2023/1061; Qin/Zhou/Gervais S&P'22 (2101.05511, H1–H5); PROF 2408.02303; F3B AFT'23 (2205.08529); Eating Sandwiches OPODIS'23 (2307.02954); Chemaya FC'24; Mamageishvili AFT'24; Yang 2024 (2405.17944); Heimbach 2022 (2202.03762); Angeris (2310.07865); FairPoS 2022/1442.

## BUILD PLAN (ordered)
1. **GATE:** re-extract the 60 attacked trades' victim sizes from chain; regenerate t8n anchor on those → pos_mev>0 on top-decile, reduction≠NaN.
2. Attacker participation constraint → rational P2S net = 0 (not −0.137).
3. Derive κ from t8n.
4. Seeds + reproducible repo + SHA-256 manifest + `make reproduce`.
5. Four-arm MC core + MC-CI + BCa bootstrap on n=60; NegBinom counts.
6. Fix Random arm (verbatim BlindPerm Pr[win], joint front+back, |B| from own blocks).
7. Analytical adversarial-blind vs MC cross-check; A2-meta metadata-residual harness.
8. Multi-slot net-MEV sign test; abandon-and-compact + throughput-loss sim.
9. Sensitivity (OAT tornado + Sobol incl. pool depth) + worst-case + no-fit statement.
10. Latency/bandwidth WAN-calibrate or downgrade + explain cliff.
11. Stats tests + Limitations + polish.

## RESIDUAL LIMITATIONS (disclose verbatim)
Local sim not testnet; measured in-slot MEV on real workload is small (claim = "removes positive EV", not the synthetic inversion); rational P2S payoff = 0 not negative; baseline adversarial-blind not uniform-random (unless BLS seed added); n=60 single-window heavy tail → wide CIs; B1 metadata leakage unless gas sealed; cross-slot MEV unchanged/possibly increased (net sign test); latency single-host lower bound; no privacy / no adaptive security; F_res deters spam not value-exceeding censorship; Qin heuristics are estimates (false positives possible).
