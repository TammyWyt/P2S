#!/usr/bin/env python3
"""Driver: rerun experiment E1 (benign-user revert cost) in a HIGH-BASE-FEE
congestion window, isolated from the low-fee dataset.

Window: 1000 blocks ending at #14,700,000 (1 May 2022, Otherdeed-mint
congestion). Base fees in this range run ~37-250 gwei (vs ~0.23 gwei in the
original low-fee run), so base >> priority -- the congestion regime that was
previously only analytical. Overhead RATIOS are price-independent and are the
deliverable here; absolute USD uses the current coin price and is NOT
meaningful for a 2022 window (ignore USD, read the ratios).

Writes to *_highfee.json so the original data/revert_*_cache/analysis files
are untouched.
"""
import revert_cost_analysis as R  # sibling module (run from scripts/ on path)

START = 14_700_000
NBLOCKS = 1000
RECEIPTS = "data/revert_receipts_highfee.json"
REASONS = "data/revert_reasons_highfee.json"
ANALYSIS = "data/revert_cost_highfee.json"

R.fetch(num_blocks=NBLOCKS, start_block=START, out_path=RECEIPTS)
R.analyze(reasons_scope="dex",
          receipts_path=RECEIPTS,
          reasons_path=REASONS,
          out_path=ANALYSIS)
