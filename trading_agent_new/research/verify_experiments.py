"""Independent persisted-evidence audit. Does not import the simulator."""
from pathlib import Path
import hashlib
import json
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def digest(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def main():
    protocol = json.loads((ROOT/'research/experiment_protocol.json').read_text())
    d=ROOT/protocol['data_directory'];out=ROOT/protocol['output_directory']
    summary=json.loads((out/'experiment_summary.json').read_text())
    registry=json.loads((out/'trial_register.json').read_text())
    assert digest(ROOT/'research/experiment_protocol.json') == registry['protocol_sha256']
    assert digest(ROOT/'research/EXPERIMENT_NOTES.preregistered.md') == registry['amendment_sha256']
    manifest=json.loads((d/'manifest.json').read_text())
    raw_closes={};raw_opens={};raw_volumes={};raw_dividends={};raw_signals={}
    for f in manifest['files']:
        assert digest(ROOT/f['raw_path'])==f['raw_sha256']
        assert digest(ROOT/f['normalized_path'])==f['normalized_sha256']
        raw=json.loads((ROOT/f['raw_path']).read_text())['chart']['result'][0]
        date=pd.to_datetime(raw['timestamp'],unit='s',utc=True).tz_convert('America/New_York').tz_localize(None).normalize()
        raw_closes[f['symbol']]=pd.Series(raw['indicators']['quote'][0]['close'],index=date)
        raw_opens[f['symbol']]=pd.Series(raw['indicators']['quote'][0]['open'],index=date)
        raw_volumes[f['symbol']]=pd.Series(raw['indicators']['quote'][0]['volume'],index=date)
        dividends=pd.Series(0.,index=date)
        assert not raw.get('events',{}).get('splits'), 'Verifier expects actual snapshot without splits'
        for event in raw.get('events',{}).get('dividends',{}).values():
            ex=pd.Timestamp(event['date'],unit='s',tz='UTC').tz_convert('America/New_York').tz_localize(None).normalize()
            dividends.loc[ex]+=event['amount']
        raw_dividends[f['symbol']]=dividends
        daily_tr=(raw_closes[f['symbol']]+dividends)/raw_closes[f['symbol']].shift(1)
        tri=daily_tr.fillna(1).cumprod()
        raw_signals[f['symbol']]=tri/tri.shift(252)>1
    rates=pd.read_csv(d/'raw/DFF.csv',index_col=0,parse_dates=True).iloc[:,0]
    all_dates=raw_closes[protocol['symbols'][0]].index
    historical_rate=pd.to_numeric(rates,errors='coerce').reindex(all_dates).ffill().shift(2)/100
    gaps=all_dates.to_series().diff().dt.days.fillna(1)
    reference=(1+historical_rate)**(gaps/365)-1
    checks={}; maximum_nav_error=0.;maximum_cash_error=0.
    for t in registry['trials']:
        tid=t['id'];daily=pd.read_csv(out/'ledgers'/f'{tid}_daily.csv',index_col='date',parse_dates=True)
        orders=pd.read_csv(out/'ledgers'/f'{tid}_orders.csv',parse_dates=['date','decision_bar_date'])
        assert (orders.decision_bar_date < orders.date).all()
        assert (daily.cash>=-1e-7).all()
        assert (orders.filled_quantity.abs()<=orders.participation_limit).all()
        assert (orders.filled_quantity.abs()<=orders.submitted_quantity.abs()).all()
        np.testing.assert_allclose(daily.risk_free,reference.reindex(daily.index),atol=1e-13)
        expected_slip=orders.filled_quantity.abs()*orders.fill_reference*t['cost_bps']/10000
        np.testing.assert_allclose(orders.slippage,expected_slip,atol=1e-7,rtol=1e-10)
        expected_fee=np.where(orders.filled_quantity!=0,np.maximum(1,.005*orders.filled_quantity.abs()),0) if t['commission'] else np.zeros(len(orders))
        np.testing.assert_allclose(orders.commission,expected_fee,atol=1e-8)
        per_day=orders.assign(buys=np.maximum(orders.filled_quantity,0)*orders.fill_price.fillna(0)+np.where(orders.filled_quantity>0,orders.commission,0),
            sells=np.maximum(-orders.filled_quantity,0)*orders.fill_price.fillna(0)-np.where(orders.filled_quantity<0,orders.commission,0),
            trade_turnover=orders.filled_quantity.abs()*orders.fill_price.fillna(0)/orders.nav_before_fill)
        per_day=per_day.groupby('date')[['buys','sells','commission','slippage','trade_turnover']].sum().reindex(daily.index,fill_value=0)
        np.testing.assert_allclose(daily.commission,per_day.commission,atol=1e-7)
        np.testing.assert_allclose(daily.slippage,per_day.slippage,atol=1e-7)
        np.testing.assert_allclose(daily.turnover,per_day.trade_turnover,atol=1e-9)
        equity=np.zeros(len(daily));dividend_entitlement=np.zeros(len(daily))
        for symbol in protocol['symbols']:
            held=daily['shares_'+symbol]
            assert (held>=0).all() and np.all(held==np.floor(held))
            filled=orders.loc[orders.symbol==symbol].groupby('date').filled_quantity.sum().reindex(daily.index,fill_value=0)
            # There are no real splits in the supplied snapshot.
            np.testing.assert_allclose(held.diff().fillna(held.iloc[0]),filled,atol=0)
            equity+=held.to_numpy()*raw_closes[symbol].reindex(daily.index).to_numpy()
            dividend_entitlement+=held.shift(1,fill_value=0).to_numpy()*raw_dividends[symbol].reindex(daily.index).to_numpy()
            os=orders.loc[orders.symbol==symbol]
            np.testing.assert_allclose(os.fill_reference,raw_opens[symbol].reindex(os.date).to_numpy(),atol=1e-8)
            expected_price=os.fill_reference*(1+np.sign(os.filled_quantity)*t['cost_bps']/10000)
            filled_mask=os.filled_quantity!=0
            np.testing.assert_allclose(os.loc[filled_mask,'fill_price'],expected_price.loc[filled_mask],atol=1e-7)
            decision_signals=raw_signals[symbol].reindex(os.decision_bar_date).to_numpy()
            np.testing.assert_array_equal(os.signal.to_numpy(),decision_signals)
            lagged_volume=raw_volumes[symbol].rolling(20).median().reindex(os.decision_bar_date).to_numpy()
            np.testing.assert_array_equal(os.participation_limit.to_numpy(),np.floor(lagged_volume*.001))
        np.testing.assert_allclose(daily.dividend_entitlement,dividend_entitlement,atol=1e-7)
        recomputed_nav=equity+daily.cash+daily.dividend_receivable+daily.unsettled_sale_proceeds
        nav_error=float(np.max(np.abs(recomputed_nav-daily.nav)))
        np.testing.assert_allclose(recomputed_nav,daily.nav,atol=1e-5,rtol=1e-10)
        div_paid=daily.dividend_receivable.shift(1,fill_value=0)+daily.dividend_entitlement-daily.dividend_receivable
        if t['settled_cash']:
            sale_paid=daily.unsettled_sale_proceeds.shift(1,fill_value=0)+per_day.sells-daily.unsettled_sale_proceeds
        else:
            sale_paid=per_day.sells
        expected_cash_change=daily.cash_interest-daily.service-per_day.buys+sale_paid+div_paid
        actual_cash_change=daily.cash.diff().fillna(daily.cash.iloc[0]-t['capital'])
        cash_error=float(np.max(np.abs(actual_cash_change-expected_cash_change)))
        np.testing.assert_allclose(actual_cash_change,expected_cash_change,atol=1e-5,rtol=1e-9)
        previous=np.r_[t['capital'],daily.nav.to_numpy()[:-1]]
        returns=daily.nav.to_numpy()/previous-1
        np.testing.assert_allclose(returns,daily['return'],atol=2e-11)
        excess=returns-daily.risk_free.to_numpy()
        sr=np.sqrt(252)*excess.mean()/excess.std(ddof=1)
        np.testing.assert_allclose(sr,summary['trials'][tid]['net_sharpe'],atol=2e-9)
        wealth=daily.nav.to_numpy()/t['capital']
        peaks=np.maximum.accumulate(np.r_[1.,wealth])[1:]
        mdd=float(np.max(1-wealth/peaks))
        np.testing.assert_allclose(mdd,summary['trials'][tid]['max_drawdown'],atol=2e-9)
        maximum_nav_error=max(maximum_nav_error,nav_error);maximum_cash_error=max(maximum_cash_error,cash_error)
        checks[tid]={'nav_cash_shares_fills_costs_returns_metrics':True,
            'raw_open_fill_dividend_trend_volume_and_rate_checks':True,
            'max_nav_error_usd':nav_error,'max_cash_error_usd':cash_error}
    checksum=json.loads((out/'evidence_checksums.json').read_text())
    all_hashes={**checksum['files'],**checksum['source_files']}
    for name,value in all_hashes.items():
        assert digest(ROOT/name)==value,f'Changed evidence: {name}'
    audit={'status':'passed','trials':len(checks),'ledger_checks':checks,
        'maximum_nav_difference_usd':maximum_nav_error,'maximum_cash_difference_usd':maximum_cash_error,
        'evidence_and_source_hashes_checked':len(all_hashes),'raw_and_normalized_hashes_checked':12,
        'protocol_and_preregistered_amendment_hashes_verified':True,
        'scope':'Independent arithmetic/provenance audit from raw provider closes and persisted ledgers; not independent market-source verification.'}
    (out/'verification.json').write_text(json.dumps(audit,indent=2)+'\n')
    print(json.dumps({k:v for k,v in audit.items() if k!='ledger_checks'},indent=2))


if __name__=='__main__':
    main()
