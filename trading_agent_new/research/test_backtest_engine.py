"""Accounting/timing tests, including independent hand-computed toy accounts."""
from dataclasses import replace
import unittest
import numpy as np
import pandas as pd
from backtest_engine import (load_market, simulate, derive_features, commission,
                             affordable_buys, settlement_lag)


class LedgerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.market = load_market()
        cls.start = cls.market.dates.searchsorted(pd.Timestamp('2016-01-01'))
        cls.trial = dict(cls.market.config['trials'][0], strategy='SPY', cost_bps=0,
                         commission=False, dividend_delay_days=30)

    def toy(self, dividend=False, split=False):
        market = self.market
        close = np.full_like(market.closes, 100.)
        div = np.zeros_like(close); splits = np.ones_like(close)
        t = self.start + 1
        if dividend:
            close[t:, 0] = 98.; div[t, 0] = 2.
        if split:
            close[t:, 0] = 50.; splits[t, 0] = 2.
        tr, r, v, c, s, med = derive_features(close, div, splits, market.volume)
        return replace(market, opens=close.copy(), closes=close, dividends=div,
                       splits=splits, tr=tr, returns=r, vol=v, cov=c, signal=s,
                       median_volume=med)

    def test_commission_and_proportional_gap_cash(self):
        self.assertEqual(commission(100), 1.)
        self.assertEqual(commission(1000), 5.)
        q, reduced = affordable_buys(np.array([6, 6]), np.array([100., 100.]), 1000., True)
        self.assertTrue(reduced)
        np.testing.assert_array_equal(q, [4, 4])
        self.assertLessEqual(q @ np.array([100., 100.]) + 2, 1000)

    def test_dividend_receivable_and_no_double_credit(self):
        market = self.toy(dividend=True)
        f, o, a = simulate(market, self.trial, stop=str(market.dates[self.start+30].date()))
        # 950 shares at $100; $1,900 receivable offsets ex-date $2 price drop.
        self.assertEqual(f.iloc[0]['shares_SPY'], 950)
        self.assertEqual(f.iloc[1]['dividend_receivable'], 1900.)
        self.assertEqual(f.iloc[1]['cash'], 5000.)
        self.assertTrue(np.allclose(f['nav'], 100000.))
        self.assertEqual(f['dividend_entitlement'].sum(), 1900.)
        self.assertEqual(f.iloc[-1]['dividend_receivable'], 0.)
        self.assertEqual(f.iloc[-1]['cash'], 6900.)
        self.assertEqual(len(o), 1)

    def test_split_preserves_equity(self):
        market = self.toy(split=True)
        f, _, _ = simulate(market, self.trial, stop=str(market.dates[self.start+3].date()))
        self.assertEqual(f.iloc[1]['shares_SPY'], 1900)
        self.assertTrue(np.allclose(f['nav'], 100000.))

    def test_charges_hand_account(self):
        market = self.toy()
        f, _, _ = simulate(market, dict(self.trial, cost_bps=5, commission=True),
                           stop=str(market.dates[self.start].date()))
        # Fixed order 950 shares, opening price100, spread47.5, commission4.75.
        self.assertAlmostEqual(f.iloc[0]['nav'], 100000-47.5-4.75)
        self.assertAlmostEqual(f.iloc[0]['cash'], 5000-47.5-4.75)

    def test_settlement_transition_and_calendar(self):
        self.assertEqual(settlement_lag(pd.Timestamp('2017-09-01')), 3)
        self.assertEqual(settlement_lag(pd.Timestamp('2017-09-05')), 2)
        self.assertEqual(settlement_lag(pd.Timestamp('2024-05-28')), 1)
        self.assertEqual(self.market.settlement_dates[pd.Timestamp('2024-05-24')], pd.Timestamp('2024-05-29'))
        self.assertEqual(self.market.settlement_dates[pd.Timestamp('2024-05-28')], pd.Timestamp('2024-05-29'))
        self.assertEqual(self.market.settlement_dates[pd.Timestamp('2024-11-08')], pd.Timestamp('2024-11-12'))

    def test_future_prices_and_events_do_not_change_past(self):
        market = self.market
        boundary = market.dates.searchsorted(pd.Timestamp('2016-03-01'))
        base, orders, _ = simulate(market, market.config['trials'][0], stop='2016-02-29')
        closes, opens = market.closes.copy(), market.opens.copy()
        div, splits, volume = market.dividends.copy(), market.splits.copy(), market.volume.copy()
        closes[boundary:] *= 3; opens[boundary:] *= 3
        div[boundary:] += 20; volume[boundary:] *= 10
        tr, r, v, c, sig, med = derive_features(closes, div, splits, volume)
        altered = replace(market, closes=closes, opens=opens, dividends=div,
                          volume=volume, tr=tr, returns=r, vol=v, cov=c,
                          signal=sig, median_volume=med)
        after, new_orders, _ = simulate(altered, market.config['trials'][0], stop='2016-02-29')
        pd.testing.assert_frame_equal(base, after, check_exact=True)
        pd.testing.assert_frame_equal(orders, new_orders, check_exact=True)


if __name__ == '__main__':
    unittest.main(verbosity=2)
