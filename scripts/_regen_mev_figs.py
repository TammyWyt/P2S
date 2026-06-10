import sys, os, shutil, importlib, time
os.environ['MPLBACKEND'] = 'Agg'
sys.path.insert(0, '/Users/tammy/Code/P2S')
os.chdir('/Users/tammy/Code/P2S')
import matplotlib
matplotlib.use('Agg')

# The block simulator uses time.sleep() per block only to mimic latency wall-clock,
# which is irrelevant to the MEV/welfare figures (latency comes from the netsim).
# No-op it so the 1000-block regeneration runs in seconds, not ~16 minutes.
time.sleep = lambda *a, **k: None

from scripts.simulation.simulator import P2SSimulator
sim = P2SSimulator()
sim.run_simulation(1000)
sim.save_results()
sim.save_ledger_json('data/block_ledger_1000.json')
sim.save_mev_comparison_json('data/mev_comparison.json')
print('SIM DONE', flush=True)

for mod in ['plots.plot_welfare', 'plots.plot_mev_comparison', 'plots.plot_attack_success_cost_reward']:
    try:
        m = importlib.import_module(mod)
        if hasattr(m, 'main'):
            m.main()
        print('PLOT', mod, 'OK', flush=True)
    except Exception as e:
        print('PLOT', mod, 'FAIL', repr(e), flush=True)

dst = '/Users/tammy/Code/P2S_Overleaf/Figures'
for f in ['mev_totals_by_type', 'cumulative_mev', 'cost_gain_comparison', 'welfare_cdf']:
    src = 'figures/%s.pdf' % f
    if os.path.exists(src):
        shutil.copy(src, '%s/%s.pdf' % (dst, f))
        print('COPIED', f, flush=True)
    else:
        print('MISSING', f, flush=True)
print('ALL DONE', flush=True)
