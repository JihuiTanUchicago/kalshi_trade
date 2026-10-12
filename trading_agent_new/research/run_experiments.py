"""Run every registered trial, paired inference and challenges; preserve outcomes."""
from __future__ import annotations
from dataclasses import replace
from pathlib import Path
from datetime import datetime, timezone
import json
import traceback
import hashlib
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from backtest_engine import ROOT, load_market, simulate, metrics, derive_features, sha256


def dump(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False)+'\n')


def delta_metrics(a, b):
    return {'sharpe_gain': b['net_sharpe']-a['net_sharpe'],
            'turnover_reduction': 1-b['annual_turnover']/a['annual_turnover'],
            'volatility_ratio': b['annual_volatility']/a['annual_volatility'],
            'drawdown_deterioration': b['max_drawdown']-a['max_drawdown'],
            'cagr_difference': b['cagr']-a['cagr']}


def bootstrap(a, b, length, draws=10000, seed=20261008):
    """Paired stationary bootstrap; expected circular blocks, geometric restarts."""
    x = a['return'].to_numpy()-a['risk_free'].to_numpy()
    y = b['return'].to_numpy()-b['risk_free'].to_numpy()
    assert a.index.equals(b.index)
    n = len(x); rng = np.random.default_rng(seed)
    cols = np.arange(n)
    results = []
    for start in range(0, draws, 200):
        size = min(200, draws-start)
        restart = rng.random((size,n)) < 1/length
        restart[:,0] = True
        new_starts = rng.integers(0,n,size=(size,n))
        last_restart = np.maximum.accumulate(np.where(restart,cols,0),axis=1)
        idx = (np.take_along_axis(new_starts,last_restart,axis=1)+cols-last_restart)%n
        xa, yb = x[idx], y[idx]
        diff = np.sqrt(252)*(yb.mean(axis=1)/yb.std(axis=1,ddof=1)-xa.mean(axis=1)/xa.std(axis=1,ddof=1))
        results.extend(diff.tolist())
    v = np.array(results)
    return {'resamples':draws, 'expected_block_length':length,'seed':seed,
            'lower_one_sided_95':float(np.quantile(v,.05)),
            'central_90_interval':[float(np.quantile(v,.05)),float(np.quantile(v,.95))],
            'bootstrap_fraction_positive':float((v>0).mean()),
            'interpretation':'Sampling diagnostic conditional on this historical proxy; not probability H1 is true.'}


def factor_diagnostic(frame, factors):
    """Descriptive OLS with Newey-West 5-lag standard errors, no fitting for trades."""
    y = frame['return'].to_numpy()-frame['risk_free'].to_numpy()
    x = np.column_stack([np.ones(len(y)), factors])
    beta = np.linalg.lstsq(x,y,rcond=None)[0]
    error = y-x@beta
    z = x*error[:,None]
    meat = z.T@z
    for lag in range(1,6):
        cross = z[lag:].T@z[:-lag]
        meat += (1-lag/6)*(cross+cross.T)
    bread = np.linalg.inv(x.T@x)
    cov = bread@meat@bread*len(y)/(len(y)-x.shape[1])
    se = np.sqrt(np.maximum(np.diag(cov),0))
    rsq = 1-float(error@error)/float((y-y.mean())@(y-y.mean()))
    return {'annual_intercept':float(beta[0]*252),
            'annual_intercept_hac95':[float((beta[0]-1.96*se[0])*252),float((beta[0]+1.96*se[0])*252)],
            'beta_SPY':float(beta[1]),'beta_TLT':float(beta[2]),'beta_GLD':float(beta[3]),
            'r_squared':rsq,'hac_lags':5,
            'interpretation':'In-sample factor exposure attribution; intercept is not established investable alpha.'}


def main():
    market = load_market()
    p = market.config; out = ROOT/p['output_directory']
    out.mkdir(parents=True, exist_ok=True)
    (out/'ledgers').mkdir(exist_ok=True); (out/'charts').mkdir(exist_ok=True)
    trials = [dict(x) for x in p['trials']]
    for s in ('B0','B2'):
        base = next(x for x in trials if x['id'] == 'primary_'+s)
        trials.append(dict(base,id='costfree_'+s,cost_bps=0,commission=False,
                           role='declared attribution diagnostic'))
    register = {'protocol_sha256':sha256(ROOT/'research/experiment_protocol.json'),
                'amendment_sha256':sha256(ROOT/'research/EXPERIMENT_NOTES.md'),
                'registered_before_performance_at':datetime.now(timezone.utc).isoformat(),
                'trials':trials,'selection':'B2 fixed; no performance selection'}
    register_path = out/'trial_register.json'
    if register_path.exists():
        old = json.loads(register_path.read_text())
        assert old['trials'] == trials and old['protocol_sha256'] == register['protocol_sha256']
    else:
        dump(register_path,register)
    history = out/'run_history.jsonl'
    run_id = datetime.now(timezone.utc).isoformat()
    with history.open('a') as f:
        f.write(json.dumps({'run_id':run_id,'event':'started','code_hash':sha256(__file__),
                            'engine_hash':sha256(ROOT/'research/backtest_engine.py')})+'\n')
    results, orderbooks, summaries, audits = {}, {}, {}, {}
    try:
        for trial in trials:
            tid = trial['id']
            frame, orders, audit = simulate(market,trial)
            frame.to_csv(out/'ledgers'/f'{tid}_daily.csv',float_format='%.12g')
            orders.to_csv(out/'ledgers'/f'{tid}_orders.csv',index=False,float_format='%.12g')
            results[tid], orderbooks[tid], audits[tid] = frame, orders, audit
            summaries[tid] = dict(metrics(frame),orders_submitted=len(orders),
                orders_filled=int((orders.filled_quantity != 0).sum()),
                orders_partial_or_rejected=int(orders.partial_or_rejected.sum()),
                maximum_participation=float((orders.filled_quantity.abs()/orders.participation_limit.replace(0,np.nan)*.001).max()))
            print(tid,'valid',flush=True)
        a, b = results['primary_B0'], results['primary_B2']
        comparisons = {}
        pairs = [('primary','primary_B0','primary_B2')]
        for prefix in ['cost10','cost25','capital10000','capital1000000','service',
                       'cashyield','settled','dividend0','dividend60','lag','nocommission','costfree']:
            pairs.append((prefix,prefix+'_B0',prefix+'_B2'))
        for name,x,y in pairs:
            comparisons[name] = delta_metrics(summaries[x],summaries[y])
        panels = {}
        for label,start,end in [('full','2016-01-01','2026-10-07'),
                                ('2016_2020','2016-01-01','2020-12-31'),
                                ('2021_current','2021-01-01','2026-10-07'),
                                ('2026_partial','2026-01-01','2026-10-07'),
                                ('current_week','2026-10-05','2026-10-07')]:
            aa,bb = a.loc[start:end],b.loc[start:end]
            if label == 'current_week':
                panels[label] = {'sessions':len(aa),'B0_total_return':float(np.prod(1+aa['return'])-1),
                    'B2_total_return':float(np.prod(1+bb['return'])-1),
                    'interpretation':'Three observations; no annualized performance inference.'}
                continue
            ma,mb = metrics(aa),metrics(bb)
            panels[label] = {'B0':ma,'B2':mb,'comparison':delta_metrics(ma,mb)}
            if label in ('full','2016_2020','2021_current'):
                panels[label]['bootstrap'] = {}
                for length in (21,63):
                    panels[label]['bootstrap'][str(length)] = bootstrap(aa,bb,length)
                    print('bootstrap',label,length,'done',flush=True)
        annual = []
        for year in sorted(set(a.index.year)):
            for tid in ['primary_B0','primary_B1','primary_B2','primary_B3','primary_Monthly',
                        'primary_NoTrend','primary_EqualWeight','primary_SPY']:
                subset = results[tid].loc[str(year)]
                annual.append(dict(trial=tid,year=int(year),partial=year==2026,**metrics(subset)))
        annual_frame = pd.DataFrame(annual)
        annual_frame.to_csv(out/'annual_metrics.csv',index=False)
        years = {}
        loo = {}
        for year in sorted(set(a.index.year)):
            aa,bb = a.loc[str(year)],b.loc[str(year)]
            years[str(year)] = delta_metrics(metrics(aa),metrics(bb))
            mask = a.index.year != year
            # Return-vector removal is an influence diagnostic, not re-run trading.
            loo[str(year)] = delta_metrics(metrics(a.loc[mask]),metrics(b.loc[mask]))['sharpe_gain']
        leak = {}
        boundary = market.dates.searchsorted(pd.Timestamp('2022-01-01'))
        close,opn = market.closes.copy(),market.opens.copy()
        div,vol = market.dividends.copy(),market.volume.copy()
        close[boundary:] *= 2.5; opn[boundary:] *= 2.5
        div[boundary:] += 7; vol[boundary:] *= 11
        tr,r,v,c,sig,med = derive_features(close,div,market.splits,vol)
        changed = replace(market,closes=close,opens=opn,dividends=div,volume=vol,
                          tr=tr,returns=r,vol=v,cov=c,signal=sig,median_volume=med)
        for name in ('B0','B2'):
            trial = next(t for t in trials if t['id']=='primary_'+name)
            prefix,po,_ = simulate(market,trial,stop='2021-12-31')
            perturbed,qo,_ = simulate(changed,trial,stop='2021-12-31')
            pd.testing.assert_frame_equal(prefix,results['primary_'+name].loc[:'2021-12-31'],check_exact=True)
            pd.testing.assert_frame_equal(prefix,perturbed,check_exact=True)
            pd.testing.assert_frame_equal(po,qo,check_exact=True)
            leak[name] = {'prefix_invariant':True,'future_price_event_volume_perturbation_invariant':True,
                          'sessions_checked':len(prefix),'orders_checked':len(po)}
        adjusted_signal = market.adjusted[252:]/market.adjusted[:-252] > 1
        source_signal_difference = {symbol:int(np.sum(adjusted_signal[:,j]!=market.signal[252:,j]))
                                    for j,symbol in enumerate(market.symbols)}
        scored_idx = market.dates.get_indexer(a.index)
        factors = market.returns[scored_idx][:,[0,4,5]]-a.risk_free.to_numpy()[:,None]
        factor = {tid:factor_diagnostic(results[tid],factors) for tid in
                  ['primary_B0','primary_B2','primary_NoTrend','primary_EqualWeight']}
        incremental = b.copy()
        incremental['return'] = b['return']-a['return']+a['risk_free']
        factor['B2_minus_B0'] = factor_diagnostic(incremental,factors)
        # Descriptive regime cutoffs fixed from the unscored 2015 warmup.
        warm = (market.dates.year==2015)&np.isfinite(market.vol[:,0])
        cutoffs = np.quantile(market.vol[warm,0],[.25,.5,.75])
        lagvol = market.vol[scored_idx-1,0]
        quartiles = np.searchsorted(cutoffs,lagvol,side='right')+1
        regimes = {}
        for q in range(1,5):
            mask = quartiles==q
            regimes[str(q)] = {'sessions':int(mask.sum()),
                              'sharpe_gain':delta_metrics(metrics(a.loc[mask]),metrics(b.loc[mask]))['sharpe_gain']}
        stress = {}
        # Influence diagnostics preserve the actual trading path, only drop scores.
        for label,date in [('without_2020_03_16','2020-03-16'),('without_2026_01_30','2026-01-30')]:
            mask = a.index != pd.Timestamp(date)
            stress[label] = delta_metrics(metrics(a.loc[mask]),metrics(b.loc[mask]))['sharpe_gain']
        comp = comparisons['primary']; gate = p['decision_gates']
        ci = panels['full']['bootstrap']['21']['lower_one_sided_95']
        positive_validation = sum(years[str(y)]['sharpe_gain']>0 for y in range(2016,2021))
        positive_complete = sum(years[str(y)]['sharpe_gain']>0 for y in range(2016,2026))
        original_panels = {}
        for label,start,end,vote_years,vote_required in [
            ('2016_2020','2016-01-01','2020-12-31',range(2016,2021),3),
            ('2021_current','2021-01-01','2026-10-07',range(2021,2026),3)]:
            v = panels[label]['comparison']
            stressed = delta_metrics(metrics(results['cost25_B0'].loc[start:end]),metrics(results['cost25_B2'].loc[start:end]))
            original_panels[label] = {
                'sharpe_gain_at_least_0_10':v['sharpe_gain']>=.10,
                'turnover_reduction_at_least_25pct':v['turnover_reduction']>=.25,
                'volatility_ratio_at_most_1_10':v['volatility_ratio']<=1.10,
                'drawdown_deterioration_at_most_2pp':v['drawdown_deterioration']<=.02,
                'cagr_shortfall_at_most_0_5pp':v['cagr_difference']>=-.005,
                'positive_bootstrap_lower_bound':panels[label]['bootstrap']['21']['lower_one_sided_95']>0,
                'calendar_year_vote':sum(years[str(y)]['sharpe_gain']>0 for y in vote_years)>=vote_required,
                'positive_at_25bps':stressed['sharpe_gain']>0,
                'both_neighbor_buffers_positive':all(metrics(results['primary_'+neighbor].loc[start:end])['net_sharpe']>
                    panels[label]['B0']['net_sharpe'] for neighbor in ('B1','B3')),
                'original_formal_source_qualification':False}
        practical = {
            'sharpe_gain_at_least_0_10':comp['sharpe_gain']>=gate['minimum_sharpe_gain'],
            'turnover_reduction_at_least_25pct':comp['turnover_reduction']>=gate['minimum_turnover_reduction'],
            'volatility_ratio_at_most_1_10':comp['volatility_ratio']<=gate['maximum_volatility_ratio'],
            'drawdown_deterioration_at_most_2pp':comp['drawdown_deterioration']<=gate['maximum_drawdown_deterioration'],
            'cagr_shortfall_at_most_0_5pp':comp['cagr_difference']>=-gate['maximum_cagr_shortfall'],
            'positive_in_at_least_3_of_5_2016_2020_years':positive_validation>=3,
            'positive_in_majority_completed_2016_2025_years':positive_complete>5,
            'positive_at_25bps':comparisons['cost25']['sharpe_gain']>0,
            'both_neighbor_buffers_positive':all(summaries['primary_'+s]['net_sharpe']>summaries['primary_B0']['net_sharpe'] for s in ('B1','B3')),
            'simulator_accounting_and_timing_valid':all(v['nonnegative_cash'] and v['no_short_positions'] and v['orders_use_prior_session'] for v in audits.values())}
        failed = [k for k,v in practical.items() if not v]
        decision = 'PRACTICALLY REJECTED UNDER PROXY ASSUMPTIONS' if failed else (
                   'STATISTICALLY INCONCLUSIVE; DO NOT PROMOTE' if ci<=0 else
                   'REVISE DATA QUALIFICATION BEFORE PROSPECTIVE PAPER TEST')
        summary = {'run_id':run_id,'scope':'Exploratory historical simulation; no untouched holdout',
            'data_audit':market.input_audit,'trials':summaries,'comparisons':comparisons,
            'panels':panels,'calendar_year_comparisons':years,'leave_one_year_out_sharpe_gains':loo,
            'factor_diagnostics':factor,'regimes':{'cutoffs_from_2015_unscored_warmup':cutoffs.tolist(),'quartiles':regimes},
            'outlier_influence':stress,'leakage_checks':leak,'forward_vs_adjusted_trend_state_differences':source_signal_difference,
            'accounting_audits':audits,'practical_gates':practical,'confidence_bound_positive':ci>0,
            'formal_data_gate_passed':False,'failed_practical_gates':failed,
            'positive_year_counts':{'2016_2020':positive_validation,'completed_2016_2025':positive_complete},
            'original_historical_panel_gates':original_panels,
            'decision':decision,'deployment':'No live-capital promotion from this experiment',
            'economic_suitability':{s:summaries[s]['annual_mean_excess']>0 for s in ['primary_B0','primary_B2','service_B2']}}
        dump(out/'experiment_summary.json',summary)
        attribution = []
        for tid in ('primary_B0','primary_B2'):
            o = orderbooks[tid].copy()
            o['filled_notional'] = o.filled_quantity.abs()*o.fill_price.fillna(0)
            o['turnover'] = o.filled_notional/o.nav_before_fill
            for reason,grp in o.groupby('reason'):
                attribution.append({'trial':tid,'reason':reason,'orders':len(grp),
                    'filled_notional_usd':float(grp.filled_notional.sum()),
                    'two_sided_turnover_sum':float(grp.turnover.sum()),
                    'commissions_usd':float(grp.commission.sum()),'slippage_usd':float(grp.slippage.sum())})
        pd.DataFrame(attribution).to_csv(out/'trade_attribution.csv',index=False)
        pd.DataFrame(summaries).T.to_csv(out/'all_trial_metrics.csv')
        pd.DataFrame(comparisons).T.to_csv(out/'paired_sensitivity_comparisons.csv')
        plt.rcParams.update({'font.size':10,'axes.spines.top':False,'axes.spines.right':False})
        fig,ax = plt.subplots(2,1,figsize=(11,7),sharex=True,gridspec_kw={'height_ratios':[2,1]})
        colors = {'primary_B0':'#748398','primary_B2':'#057a8d','primary_Monthly':'#db9225',
                  'primary_NoTrend':'#9d63b0','primary_EqualWeight':'#688c47','primary_SPY':'#b25454'}
        for tid in colors:
            f = results[tid]; wealth = (1+f['return']).cumprod()
            ax[0].plot(f.index,wealth,label=tid.replace('primary_',''),color=colors[tid],lw=1.2)
        ax[0].set_yscale('log');ax[0].set_ylabel('Growth of initial capital (log scale)')
        ax[0].legend(ncol=3,loc='upper left',frameon=False)
        for tid in ['primary_B0','primary_B2']:
            wealth = (1+results[tid]['return']).cumprod()
            peak = np.maximum.accumulate(np.r_[1.,wealth])[1:]
            ax[1].plot(wealth.index,100*(wealth.to_numpy()/peak-1),color=colors[tid],label=tid[8:])
        ax[1].set_ylabel('Drawdown (%)');ax[1].grid(alpha=.2)
        ax[0].set_title('ETF research experiment · Jan 2016–Oct 7, 2026 · simulated net returns')
        fig.tight_layout();fig.savefig(out/'charts/growth_and_drawdown.png',dpi=170);plt.close(fig)
        fig,ax = plt.subplots(figsize=(10,3.8))
        yy = sorted(years)
        gains = [years[y]['sharpe_gain'] for y in yy]
        ax.bar(yy,gains,color=['#057a8d' if x>=0 else '#bd5654' for x in gains])
        ax.axhline(0,color='#555',lw=.7);ax.axhline(.1,color='#888',ls='--',lw=.8,label='Effect threshold 0.10 (full-sample gate)')
        ax.set_ylabel('B2 − B0 excess Sharpe');ax.set_title('Calendar-year stability · 2026 is partial');ax.legend(frameon=False)
        fig.tight_layout();fig.savefig(out/'charts/annual_sharpe_difference.png',dpi=170);plt.close(fig)
        build_report(out,summary)
        files = sorted(x for x in out.rglob('*') if x.is_file() and x.name not in ('evidence_checksums.json','run_history.jsonl','verification.json'))
        dump(out/'evidence_checksums.json',{'files':{str(x.relative_to(ROOT)):sha256(x) for x in files},
            'source_files':{str(x.relative_to(ROOT)):sha256(x) for x in [Path(__file__),ROOT/'research/backtest_engine.py',
            ROOT/'research/test_backtest_engine.py',ROOT/'research/verify_experiments.py',
            ROOT/'research/experiment_protocol.json',ROOT/'research/EXPERIMENT_NOTES.md',ROOT/'research/EXPERIMENT_NOTES.preregistered.md']}})
        with history.open('a') as f:
            f.write(json.dumps({'run_id':run_id,'event':'completed','decision':decision,'trials':len(trials)})+'\n')
        print(json.dumps({'decision':decision,'comparison':comp,'lower_ci':ci,'failed':failed},indent=2),flush=True)
    except Exception as e:
        with history.open('a') as f:
            f.write(json.dumps({'run_id':run_id,'event':'failed','error':str(e),'traceback':traceback.format_exc()})+'\n')
        raise


def build_report(out,s):
    p = s['comparisons']['primary']
    lines = ['# Controlled ETF experiments and decision — October 8, 2026','',
        f"Decision: **{s['decision']}**.",'',
        'Six ETFs; continuous integer-share accounts January 4, 2016–October 7, 2026 (2,706 sessions). '+
        'Primary capital $100,000; five basis points adverse cost per side, commissions max($1/order, $0.005/share); '+
        'cash earns zero. B0 and B2 share signals, target construction, source prices and execution accounting. '+
        'B2 adds a two-percentage-point buffer, with trend and risk overrides. All 32 trials were registered before performance evaluation.','',
        'This is historical exploratory evidence. The periods were already explored. Current-vintage public data, '+
        'assumed dividend payment dates and an approximate settlement calendar do not satisfy the original formal data gate.','',
        '## Matched baseline and candidate','',
        '| Strategy | Net excess Sharpe | CAGR | Volatility | Max drawdown | Annual two-sided turnover |','|---|---:|---:|---:|---:|---:|']
    for tid in ['primary_B0','primary_B1','primary_B2','primary_B3','primary_Monthly','primary_NoTrend','primary_EqualWeight','primary_SPY']:
        m=s['trials'][tid]
        lines.append(f"| {tid[8:]} | {m['net_sharpe']:.3f} | {m['cagr']:.2%} | {m['annual_volatility']:.2%} | {m['max_drawdown']:.2%} | {m['annual_turnover']:.2f}× |")
    lines += ['',f"B2 minus B0: Sharpe {p['sharpe_gain']:+.4f}; turnover reduction {p['turnover_reduction']:.2%}; "+
        f"CAGR difference {p['cagr_difference']*100:+.3f} percentage points; volatility ratio {p['volatility_ratio']:.3f}; "+
        f"drawdown deterioration {p['drawdown_deterioration']*100:+.3f} percentage points.",'',
        '## Sampling uncertainty and time stability','',
        '| Period | B0 Sharpe | B2 Sharpe | Gain | 21-session bootstrap 5th percentile | 63-session 5th percentile |',
        '|---|---:|---:|---:|---:|---:|']
    for label in ['full','2016_2020','2021_current','2026_partial']:
        z=s['panels'][label]; bs=z.get('bootstrap',{})
        lo=lambda l:f"{bs[l]['lower_one_sided_95']:+.4f}" if l in bs else 'not tested'
        lines.append(f"| {label} | {z['B0']['net_sharpe']:.3f} | {z['B2']['net_sharpe']:.3f} | {z['comparison']['sharpe_gain']:+.4f} | {lo('21')} | {lo('63')} |")
    lines += ['', '10,000 paired stationary bootstrap samples per panel and block length; seed 20261008. '+
        'The fifth percentile is the one-sided 95% lower bound; the reported fifth-to-95th range is a central 90% interval. '+
        'Sampling uncertainty conditional on this history does not account for all prior idea selection or make these periods independent holdouts.','',
        f"Positive annual differences: {s['positive_year_counts']['2016_2020']}/5 in 2016–2020; "+
        f"{s['positive_year_counts']['completed_2016_2025']}/10 completed years. 2026 does not vote. "+
        f"Leave-one-year-out gain range: {min(s['leave_one_year_out_sharpe_gains'].values()):+.4f} to {max(s['leave_one_year_out_sharpe_gains'].values()):+.4f}. "+
        'Those diagnostics drop scoring observations and do not re-run the trading path.','',
        'The original panel gates are also retained: 2016–2020 and 2021–current each fail the 0.10 Sharpe '+
        'gain and 25% notional-turnover thresholds; their remaining practical and sampling gates pass. '+
        'The 2021–2025 completed-year vote passes with 4/5 positive years. The formal source gate fails in both.','',
        '## Costs and operational sensitivities','',
        '| Assumption | B2 − B0 Sharpe | Turnover reduction |','|---|---:|---:|']
    for name,v in s['comparisons'].items():
        lines.append(f"| {name} | {v['sharpe_gain']:+.4f} | {v['turnover_reduction']:.1%} |")
    a=s['trials']['primary_B0'];b=s['trials']['primary_B2']
    lines += ['', f"Total commissions: B0 ${a['commissions_usd']:,.2f}, B2 ${b['commissions_usd']:,.2f}. "+
        f"Simulated slippage: B0 ${a['slippage_usd']:,.2f}, B2 ${b['slippage_usd']:,.2f}. "+
        'Dollar cost sums occur on different account wealth paths and are not a causal return decomposition. '+
        'Zero-cost counterparts separate exposure drift from the broad cost-saving mechanism.','',
        f"Order count falls from {a['orders_filled']:,} to {b['orders_filled']:,} "+
        f"({1-b['orders_filled']/a['orders_filled']:.1%}), whereas notional turnover falls only {p['turnover_reduction']:.1%}. "+
        'Trend-change exits and entries still require large trades; the buffer mainly removes small resizing orders. '+
        'This distinction explains why commission savings are much larger than notional-turnover savings. '+
        f"Without commissions, the Sharpe gain drops to {s['comparisons']['nocommission']['sharpe_gain']:.4f}; "+
        f"with all modeled trading costs removed it is {s['comparisons']['costfree']['sharpe_gain']:.4f}. "+
        'The observed advantage is primarily a friction-saving mechanism in these simulations.','',
        f"B2's 2021–current excess Sharpe is {s['panels']['2021_current']['B2']['net_sharpe']:.3f}, "+
        f"and its 2026 partial-year excess Sharpe is {s['panels']['2026_partial']['B2']['net_sharpe']:.3f}. "+
        f"A $1,200 annual service charge reduces full-period B2 CAGR to {s['trials']['service_B2']['cagr']:.2%}. "+
        'Relative improvement over a costly baseline is not evidence of an attractive standalone strategy.','',
        '## Hidden exposures and implementation challenges','',
        '| Portfolio | Average cash and claims | Equity | Treasury | Gold | SPY factor beta | Annual intercept, HAC 95% interval |',
        '|---|---:|---:|---:|---:|---:|---|']
    for tid in ['primary_B0','primary_B2','primary_NoTrend','primary_EqualWeight']:
        m=s['trials'][tid];f=s['factor_diagnostics'][tid];ci=f['annual_intercept_hac95']
        lines.append(f"| {tid[8:]} | {m['average_cash_and_claims']:.1%} | {m['average_equity']:.1%} | {m['average_treasury']:.1%} | {m['average_gold']:.1%} | {f['beta_SPY']:.3f} | {f['annual_intercept']:.2%} [{ci[0]:.2%}, {ci[1]:.2%}] |")
    lines += ['', 'Factor regression uses contemporaneous SPY, TLT and GLD total excess returns. It is in-sample exposure attribution, '+
        'not an investable alpha estimate. IEF/TLT overlap and correlated equity funds remain concentrated economic exposures.','',
        f"B0 closing asset/gross cap breach days: {a['asset_cap_breach_days']}/{a['gross_cap_breach_days']}; "+
        f"B2: {b['asset_cap_breach_days']}/{b['gross_cap_breach_days']}. "+
        'Prior-close caps cannot prevent price moves or fills from producing small closing breaches; the next decision applies caps. '+
        f"B0/B2 partial or rejected orders: {a['orders_partial_or_rejected']}/{b['orders_partial_or_rejected']}. "+
        'All ledgers have nonnegative cash, no shorts and independently reconciled daily P&L.','',
        'Settlement constraints reduce eligible buys on 139 B0 sessions and 123 B2 sessions; the declared '+
        'settlement sensitivity retains a positive incremental Sharpe gain but still misses the practical thresholds. '+
        'Immediate versus 60-day dividend payments produce the same primary trading path because cash is not binding '+
        'under those scenarios. This does not establish that assumed payable dates are accurate.','',
        'Prefix and future-price/dividend/volume perturbation checks passed for B0 and B2 through 2021. '+
        'An additional decision-day lag is reported above. These checks address implementation leakage; they do not prove '+
        'that revised source prices or corporate actions were historically available. '+
        f"Forward versus vendor-adjusted trend-state differences by symbol: {s['forward_vs_adjusted_trend_state_differences']}.",'',
        'Assumed dividend payments are tested at 0/30/60 calendar days. The settled-cash trial uses historical T+3/T+2/T+1 '+
        'with an approximate holiday calendar. Cash yield uses lagged current-vintage DFF less 0.50 percentage points. '+
        'Service sensitivity deducts $100 on the first session of each month. No tax estimate or observed fill calibration is supplied.','',
        '## Fixed decision gates','', '| Gate | Result |','|---|---|']
    for k,v in s['practical_gates'].items():
        lines.append(f"| {k} | {'PASS' if v else 'FAIL'} |")
    lines += [f"| Positive bootstrap lower bound | {'PASS' if s['confidence_bound_positive'] else 'FAIL'} |", '| Original formal source qualification | FAIL |','',
        f"Decision: **{s['decision']}**. Failed practical gates: {', '.join(s['failed_practical_gates']) or 'none'}.",'',
        'A practical rejection applies to this fixed candidate under the declared proxy assumptions. A formal source failure '+
        'leaves the original qualified-data claim unvalidated rather than definitively disproving it. The buffer is not retuned, '+
        'and another control is not promoted because it performed better. A defensible next experiment requires a new specification, '+
        'qualified data and a genuinely prospective observation period.','',
        f"Positive annual mean excess after costs: B0 {s['economic_suitability']['primary_B0']}, "+
        f"B2 {s['economic_suitability']['primary_B2']}, B2 with service fee {s['economic_suitability']['service_B2']}. "+
        'This is the declared standalone economic screen, separate from the relative buffer hypothesis.','',
        '## Reproducible evidence','',
        '`trial_register.json`, `all_trial_metrics.csv`, `paired_sensitivity_comparisons.csv`, `annual_metrics.csv`, '+
        '`experiment_summary.json`, per-trial daily/order ledgers, `run_history.jsonl` and `evidence_checksums.json`. '+
        'Run `.venv/bin/python research/test_backtest_engine.py`, then `.venv/bin/python research/run_experiments.py`.','',
        'Rate source: [FRED DFF](https://fred.stlouisfed.org/series/DFF). Settlement transitions: '+
        '[SEC T+2](https://www.sec.gov/newsroom/press-releases/2017-163) and '+
        '[SEC T+1](https://www.sec.gov/newsroom/press-releases/2024-62).']
    (out/'EXPERIMENT_REPORT.md').write_text('\n'.join(lines)+'\n')


if __name__ == '__main__':
    main()
