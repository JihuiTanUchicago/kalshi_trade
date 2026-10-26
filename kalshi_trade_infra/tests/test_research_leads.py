"""Data-first research (services.research_leads): the scan finds planted edges and stays quiet on noise."""
import random
from datetime import datetime, timezone
from types import SimpleNamespace

from app.trading.markets import Contract, Snapshot
from app.services import research_leads as rl

T0 = 1_760_000_000


def _fee(qty, price):
    return 0.07 * price * (1 - price) + 0.01 / qty


def _ds(edge, n_events=600, strikes=3, seed=0, noise_feats=6):
    """15-minute events, `strikes` contracts each, a snapshot per minute. Every quote is fair (YES
    settles at the mid) except, with `edge`, late-life mid-priced contracts whose `flow` feature
    sits in its top tercile settle YES `edge` more often than their price says."""
    rng = random.Random(seed)
    frames, results = [], {}
    for e in range(n_events):
        open_ts = T0 + e * 900
        close = datetime.fromtimestamp(open_ts + 900, tz=timezone.utc)
        cons = []
        for k in range(strikes):
            mid = rng.uniform(0.3, 0.7)
            flow = rng.uniform(-1, 1)
            hot = edge and flow > 1 / 3
            cons.append((Contract("E%d-%d" % (e, k), 100.0 + k, close, "KXBTC15M"), mid, flow))
            p = min(0.99, mid + (edge if hot else 0.0))
            results["E%d-%d" % (e, k)] = "yes" if rng.random() < p else "no"
        for m in range(15):
            ts = open_ts + 60 * m
            snaps = []
            for con, mid, flow in cons:
                feats = {"tte_min": 15.0 - m, "flow_imb_60s": flow if m >= 10 else rng.uniform(-1, 1)}
                for j in range(noise_feats):
                    feats["noise_%d" % j] = rng.gauss(0, 1)
                snaps.append(Snapshot(con, ts, mid - 0.005, mid + 0.005, feats))
            frames.append((ts, snaps))
    return SimpleNamespace(frames=frames, results=results, start_ts=T0, end_ts=T0 + n_events * 900)


def _scan(ds):
    return rl.scan(ds, _fee, 0.01, val_days=(ds.end_ts - ds.start_ts) / 86400 * 25 / 60, z_req=1.645)


def test_a_planted_conditional_edge_is_found_with_its_filter_and_side():
    res = _scan(_ds(edge=0.15))
    assert res["leads"], res["tests"]
    top = res["leads"][0]
    assert (top["feature"], top["tercile"], top["side"], top["life"]) == ("flow_imb_60s", "top", "yes", "late")
    assert top["net_c"] > 5 and 0 < top["power"] <= 1
    text = rl.block(res)
    assert "L1: late life, mid price, flow_imb_60s >" in text and "buy YES" in text


def test_fair_quotes_produce_no_lead_and_say_so():
    found = sum(len(_scan(_ds(edge=0.0, seed=s))["leads"]) for s in range(3))
    assert found == 0
    res = _scan(_ds(edge=0.0, seed=9))
    assert "NO cell survives" in rl.block(res)


def test_contracts_of_one_event_count_once():
    res = _scan(_ds(edge=0.15, strikes=3))
    top = res["leads"][0]
    assert top["contracts"] > top["events"]


def test_arms_split_by_run_id(monkeypatch):
    monkeypatch.setattr(rl, "LEADS_SHARE", 0.5)
    on = sum(rl.in_leads_arm(i) for i in range(1, 401))
    assert 140 < on < 260
    monkeypatch.setattr(rl, "LEADS_SHARE", 0.0)
    assert not any(rl.in_leads_arm(i) for i in range(1, 50))


def test_power_line_reads_validation_power():
    assert "gives 63% power" in rl.power_line({"power": 0.63, "mu": 0.03, "n_val_expected": 210})
    assert "not positive" in rl.power_line({"power": 0.0, "mu": -0.01})
    assert rl.power_line({}) == ""


def test_a_leads_arm_run_shows_the_table_the_counterparty_rule_and_power(monkeypatch):
    from app.trading import backtest
    from app.research import agent
    from tests.test_app_backtest import _dataset
    ds = _dataset()
    run = {"market": "btc15m", "prompt": "x"}
    plain = agent._research_prompt(run, ds, [], 4)
    assert "LEADS (" not in plain and "COUNTERPARTY RULE" not in plain
    res = rl.scan_dataset(ds)
    armed = agent._research_prompt(dict(run, _leads=rl.block(res), _leads_arm=True), ds, [], 4)
    assert "LEADS (" in armed and "COUNTERPARTY RULE" in armed
    ins = backtest.metrics([], 10.0, 1.0)
    ins.pop("_curve", None)
    t = {"thesis": "x", "spec": {}, "in_sample": ins,
         "power_line": rl.power_line({"power": 0.4, "mu": 0.02, "n_val_expected": 90})}
    assert "PROJECTED VALIDATION: ~90 validation trades" in agent._develop_prompt(run, t, [], 0, ds)


def test_the_run_card_and_watch_split_the_leads_arm():
    from app.research import rsi
    from app.research_watch import screen_ab
    run = {"id": 3, "model": "opus-4-6", "status": "succeeded", "input_tokens": 1000, "output_tokens": 100,
           "hypotheses_tried": 8}
    card = rsi.run_card(run, [{"kind": "verdict", "message": "", "data": rl.summary(True, {"tests": 900,
                                                                                         "leads": [{}]})}])
    other = rsi.run_card(dict(run, id=4), [{"kind": "verdict", "message": "", "data": rl.summary(False, None)}])
    assert card["leads_arm"] == "leads" and other["leads_arm"] == "control"
    ab = screen_ab([card, other], "leads_arm")
    assert set(ab) == {"leads", "control"} and ab["leads"]["explored"] == 8
