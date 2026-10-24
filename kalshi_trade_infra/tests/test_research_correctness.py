"""Three research-loop correctness/reliability fixes:

FIX 1 — the research prompt is MARKET-AWARE: a non-BTC run is never told it trades Bitcoin, and an
        event/non-price market is steered confidently to a hand-written `code`+fit model.
FIX 2 — a hand-written fitted model round-trips through fit()'s frozen params (pickle+base64), so
        richer models (random forest / GBM / ensembles) are genuinely usable, not logistic-only.
FIX 3 — the uniform anti-stuck guarantee: an informative watchdog message and a progress-gated
        background heartbeat beater (the model-stall slice lives in test_llm_stream.py).
"""
import threading
import time
from datetime import timedelta

import pytest

from app import agent, backtest, sandbox
from app.markets import MARKETS


# -- FIX 1: market-aware prompt --------------------------------------------------------------------


def _mini_ds(market_key):
    m = MARKETS[market_key]
    return backtest.Dataset(market=m, frames=[], results={}, start_ts=0, end_ts=86400, contracts=0)


def test_non_btc_profile_never_mentions_bitcoin():
    # The live bug: an nhl_game run was TOLD it traded Bitcoin. Every non-crypto market's profile
    # must be free of BTC/Bitcoin/Coinbase framing.
    for mk in ("nhl_game", "high_ny", "tao_sn64"):
        if mk not in MARKETS:
            continue
        p = agent._market_profile(mk)
        assert "Bitcoin" not in p and "BTC" not in p and "Coinbase" not in p, "%s leaked BTC framing" % mk


def test_btc_profile_still_reads_as_bitcoin():
    p = agent._market_profile("btc15m")
    assert "BTC" in p and "strike" in p and "Coinbase" in p  # the crypto run is unchanged


def test_event_market_profile_steers_to_code_fit_not_gbm():
    # The NHL failure: agent rejected gbm (correctly) then gave up on `code`. The profile must say
    # gbm doesn't apply AND point confidently at code+fit as first-class — not a dead end.
    p = agent._market_profile("nhl_game")
    assert "gbm" in p and "does NOT apply" in p
    assert "first-class" in p.lower() and "fit(window)" in p
    assert "not a reason to call a thesis dead" in p or "NOT a reason" in p


def test_research_prompt_for_sports_is_market_aware():
    run = {"market": "nhl_game", "prompt": "find an edge", "direction": "momentum"}
    prompt = agent._research_prompt(run, _mini_ds("nhl_game"), [], count=3)
    # No hardcoded-BTC FRAMING claiming the current market is Bitcoin (btc15m may still appear as a
    # cross-market peer option — that's a legitimate relative-value leg, not framing).
    assert "trading Kalshi Bitcoin" not in prompt and "if BTC settles" not in prompt
    assert "Coinbase" not in prompt  # no crypto price-feed framing for a sports market
    assert "Market profile" in prompt and "NHL" in prompt
    assert "BTC moves" not in prompt                       # the momentum lens is generalized
    assert "does NOT apply" in prompt and "fit(window)" in prompt  # event -> code+fit steering


# -- FIX 2: a hand-written fitted model round-trips via pickle+base64 ------------------------------


needs_confiner = pytest.mark.skipif(not sandbox.os_sandbox_available(),
                                    reason="no OS-level sandbox (sandbox-exec/bwrap/firejail) here")


def test_pickle_base64_in_allowlist():
    # The guide tells agents to pickle+base64 a fitted model; both MUST be importable, or the whole
    # richer-model path is dead on arrival (they were blocked before this fix).
    assert "pickle" in sandbox.STRATEGY_ALLOWED_IMPORTS
    assert "base64" in sandbox.STRATEGY_ALLOWED_IMPORTS
    sandbox.validate_strategy_code("import pickle, base64\ndef signals(w): return []")
    # sklearn ensembles validate statically too (the models the agent hand-writes).
    sandbox.validate_strategy_code(
        "from sklearn.ensemble import RandomForestClassifier\ndef signals(w): return []")


@needs_confiner
def test_fitted_model_round_trips_through_frozen_params():
    # The channel richer models depend on: fit() trains on the research window and PICKLES+base64's
    # its result into params; signals() reloads and predicts — no refit (the leakage freeze). Pure
    # Python here (a hand-rolled OLS) so it runs on every platform; the exact pickle+base64 channel
    # carries a RandomForest/GBM identically (see the sklearn test below). This path was DEAD before
    # the fix — pickle/base64 weren't importable in the sandbox.
    code = (
        "import pickle, base64\n"
        "def fit(window):\n"
        "    xs = [0.0,1.0,2.0,3.0,4.0]; ys = [1.0,3.0,5.0,7.0,9.0]\n"   # y = 2x + 1
        "    n = len(xs); sx = sum(xs); sy = sum(ys)\n"
        "    sxx = sum(x*x for x in xs); sxy = sum(x*y for x,y in zip(xs,ys))\n"
        "    b = (n*sxy - sx*sy) / (n*sxx - sx*sx); a = (sy - b*sx)/n\n"
        "    return {'model': base64.b64encode(pickle.dumps({'a':a,'b':b})).decode()}\n"
        "def signals(window):\n"
        "    m = pickle.loads(base64.b64decode(window['params']['model']))\n"
        "    out = []\n"
        "    for f in window['frames']:\n"
        "        s = m['a'] + m['b']*10.0\n"   # predict at x=10 -> 21
        "        out.append([{'ticker':'t','side':'yes','score':s}] if f['contracts'] else [])\n"
        "    return out\n"
    )
    win = {"market": "btc15m", "frames": [{"ts": 1, "contracts": [{"ticker": "t"}]}]}
    params = sandbox.run_strategy_fit(code, win, cpu_s=10, wall_s=30)
    import json
    assert "model" in params and len(json.dumps(params)) < sandbox.STRATEGY_MAX_PARAMS
    win2 = dict(win); win2["params"] = params
    sig = sandbox.run_strategy_signals(code, win2, cpu_s=10, wall_s=30)
    assert sig and sig[0] and sig[0][0]["side"] == "yes"       # the frozen model reloaded
    assert abs(sig[0][0]["score"] - 21.0) < 1e-6              # and predicted from frozen params


@needs_confiner
def test_sklearn_ensemble_fits_in_sandbox_or_documents_the_limit():
    # The richer-model goal: a RandomForest FIT runs in the sandbox. On the Linux prod sandbox it
    # succeeds; on the macOS dev box the secret-mask hides stdlib `secrets` (a known dev-only
    # limitation), so we skip there rather than fail — the round-trip CHANNEL is proven above.
    code = (
        "import numpy as np, pickle, base64\n"
        "from sklearn.ensemble import RandomForestClassifier\n"
        "def fit(window):\n"
        "    rng = np.random.RandomState(0)\n"
        "    X = rng.rand(200,3); y = (X[:,0] > 0.5).astype(int)\n"
        "    m = RandomForestClassifier(n_estimators=25, max_depth=3, random_state=0).fit(X,y)\n"
        "    return {'model': base64.b64encode(pickle.dumps(m)).decode()}\n"
        "def signals(window):\n"
        "    m = pickle.loads(base64.b64decode(window['params']['model']))\n"
        "    return [[] for _ in window['frames']]\n"
    )
    win = {"market": "btc15m", "frames": [{"ts": 1, "contracts": []}]}
    try:
        params = sandbox.run_strategy_fit(code, win, cpu_s=30, wall_s=90)
    except sandbox.SandboxError as e:
        if "secrets" in str(e):
            pytest.skip("macOS dev sandbox masks stdlib `secrets`; RF fits on the Linux prod sandbox")
        raise
    import json
    assert "model" in params and len(json.dumps(params)) < sandbox.STRATEGY_MAX_PARAMS


# -- FIX 3: uniform anti-stuck watchdog ------------------------------------------------------------


def test_abandoned_run_message_is_informative():
    captured = {}

    class _Cur:
        rowcount = 1
        def execute(self, sql, params):
            captured["sql"], captured["params"] = sql, params  # last execute wins (the UPDATE)
        def fetchall(self):
            # one stale run with no checkpointed progress -> the neutral stopped path (not resumable)
            return [{"id": 1, "kind": "research", "resume_count": 0, "checkpoint_json": None}]

    from app import repository as repo
    repo.fail_abandoned_runs(_Cur(), timedelta(seconds=240))
    # An interrupted run is STOPPED, never failed, and says it was interrupted — not a scary error.
    assert "status='stopped'" in " ".join(captured["sql"].split())
    msg = captured["params"][0]
    assert "interrupted before it explored" in msg and "start a new one" in msg
    assert "status='stopped'" in captured["sql"]
    assert captured["params"][1:3] == (0, 0)
    assert msg != "The agent stopped responding."  # the old generic message is gone


def test_extra_research_libs_allowlisted():
    # New hand-written-model libraries the proposer is told about must be importable in the sandbox
    # (static gate = parse only, so this passes before they're installed on the box).
    for mod in ("hmmlearn", "choix", "linearmodels", "pmdarima", "ruptures", "networkx"):
        assert mod in sandbox.STRATEGY_ALLOWED_IMPORTS
        sandbox.validate_strategy_code("import %s\ndef signals(w): return []" % mod)


def test_research_eval_null_baseline_and_discovery_efficiency():
    from app import research_eval as E
    # Calibration: on a pure-noise market, mechanical random search makes ~no validated discovery.
    noise = E.run_episode("null", E.random_spec, E.noise_backtest(seed=1), budget=24, seed=1)
    assert noise.discovery_efficiency <= 0.1
    # Power + headline control: an agent that finds the planted edge out-discovers the null baseline.
    cmp = E.null_vs_agent("oracle", E.oracle_propose, E.planted_edge_backtest(seed=2), budget=16, seed=2)
    assert cmp["agent"]["validated"] >= 1 and cmp["agent_beats_null"]
    s = E.random_spec(__import__("random").Random(0))
    assert "entry" in s and s["market"] in MARKETS


def test_heartbeat_pump_beats_while_fresh_and_stops_when_stale(monkeypatch):
    beats = []

    class _Cur:
        def __enter__(self): return self
        def __exit__(self, *a): return False

    class _Conn:
        def cursor(self): return _Cur()
        def commit(self): pass
        def rollback(self): pass
        def close(self): pass

    import data_pipeline.common as dpc
    monkeypatch.setattr(dpc, "get_db_conn", lambda: _Conn())
    monkeypatch.setattr(agent.repo, "heartbeat", lambda c, rid: beats.append(rid))
    monkeypatch.setattr(agent, "RUN_HEARTBEAT_EVERY", 0.02)
    monkeypatch.setattr(agent, "RUN_STALL_SECONDS", 0.1)

    progress = [time.monotonic()]
    stop = threading.Event()
    th = threading.Thread(target=agent._heartbeat_pump, args=(7, progress, stop), daemon=True)
    th.start()
    try:
        for _ in range(10):          # keep the main thread "progressing"
            progress[0] = time.monotonic()
            time.sleep(0.02)
        assert beats, "a progressing run must be beaten"
        # Stop progressing: past the stall grace the beater must give up so the watchdog can reap it.
        time.sleep(0.25)
        mid = len(beats)
        time.sleep(0.25)
        assert len(beats) - mid <= 1, "beater kept a frozen run alive (%d extra beats)" % (len(beats) - mid)
        assert beats[-1] == 7
    finally:
        stop.set()
        th.join(1)
