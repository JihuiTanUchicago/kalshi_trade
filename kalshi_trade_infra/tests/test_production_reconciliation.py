"""Offline regressions for reliability behavior recovered from deployed source."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from decimal import Decimal
import importlib.util
from pathlib import Path
import re
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app import repository
from app.adapters.llm import llm, models_catalog
from app.adapters.stripe import billing
from app.research import gatekeeper, partitions


@pytest.fixture
def fallback_state(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(llm, "_MODEL_COOLDOWN", {})
    monkeypatch.setattr(llm, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    return clock


def test_daily_quota_fallback_skips_exhausted_model_until_cooldown_expires(monkeypatch, fallback_state):
    preferred, secondary = models_catalog.fallback_chain_from(models_catalog.default().model_id)[:2]
    successful = ("accepted", {"input_tokens": 12, "output_tokens": 7})
    call = Mock(side_effect=[llm.LLMThrottled("Too many tokens per day"), successful, successful, successful])
    monkeypatch.setattr(llm, "_bedrock_once", call)
    sink = Mock()
    assert llm._bedrock("system", [], preferred, sink) == successful
    assert [args.args[2] for args in call.call_args_list] == [preferred, secondary]
    assert all(args.args[3] is sink for args in call.call_args_list)
    assert llm._MODEL_COOLDOWN[preferred] == 100.0 + llm._DAILY_COOLDOWN_SEC
    assert llm._bedrock("system", [], preferred, sink) == successful
    assert call.call_args.args[2] == secondary
    fallback_state[0] += llm._DAILY_COOLDOWN_SEC + 1
    assert llm._bedrock("system", [], preferred, sink) == successful
    assert call.call_args.args[2] == preferred


def test_transient_capacity_fallback_does_not_create_daily_cooldown(monkeypatch, fallback_state):
    preferred = models_catalog.default().model_id
    call = Mock(side_effect=[llm.LLMThrottled("ThrottlingException: burst capacity"), ("ok", {}), ("recovered", {})])
    monkeypatch.setattr(llm, "_bedrock_once", call)
    assert llm._bedrock("system", [], preferred)[0] == "ok"
    assert not llm._MODEL_COOLDOWN
    assert llm._bedrock("system", [], preferred)[0] == "recovered"
    assert call.call_args.args[2] == preferred


def test_noncapacity_failure_does_not_hide_access_or_infrastructure_errors(monkeypatch, fallback_state):
    failure = llm.LLMError("access configuration refused")
    call = Mock(side_effect=failure)
    monkeypatch.setattr(llm, "_bedrock_once", call)
    with pytest.raises(llm.LLMError) as caught:
        llm._bedrock("system", [], models_catalog.default().model_id)
    assert caught.value is failure
    assert call.call_count == 1
    assert not llm._MODEL_COOLDOWN


def test_all_models_cooling_down_are_rechecked_instead_of_refusing_without_attempt(monkeypatch, fallback_state):
    chain = models_catalog.fallback_chain_from(models_catalog.default().model_id)
    llm._MODEL_COOLDOWN.update({model: 9999 for model in chain})
    call = Mock(return_value=("capacity restored", {}))
    monkeypatch.setattr(llm, "_bedrock_once", call)
    assert llm._bedrock("system", [], chain[0])[0] == "capacity restored"
    assert call.call_args.args[2] == chain[0]


def test_exhausted_chain_preserves_typed_capacity_error(monkeypatch, fallback_state):
    chain = models_catalog.fallback_chain_from(models_catalog.default().model_id)
    failures = [llm.LLMThrottled("capacity unavailable %s" % index) for index in range(len(chain))]
    call = Mock(side_effect=failures)
    monkeypatch.setattr(llm, "_bedrock_once", call)
    with pytest.raises(llm.LLMThrottled) as caught:
        llm._bedrock("system", [], chain[0])
    assert caught.value is failures[-1]
    assert [args.args[2] for args in call.call_args_list] == chain


@pytest.mark.parametrize("key", ["opus-4-5", "sonnet-4-5", "haiku-4-5", "nova-pro", "llama-3-3-70b"])
def test_fallback_catalog_retains_model_identity_and_exact_pricing_metadata(key):
    choice = models_catalog.resolve(key)
    chain = models_catalog.fallback_chain_from(choice.model_id)
    assert chain[0] == choice.model_id
    assert models_catalog.price_for_model_id(choice.model_id) == (choice.price_in, choice.price_out)
    assert choice.price_in > 0 and choice.price_out > 0
    if key in models_catalog.FALLBACK_ORDER:
        assert chain == [mid for item in models_catalog.FALLBACK_ORDER[models_catalog.FALLBACK_ORDER.index(key):]
                         for mid in (models_catalog.MODELS[item].model_id,
                                     models_catalog.global_twin(models_catalog.MODELS[item].model_id))]
    else:
        assert chain == [choice.model_id]
    assert models_catalog.fallback_chain_from("private-unregistered-model") == ["private-unregistered-model"]
    assert sum(item["default"] for item in models_catalog.catalog_json()) == 1


@pytest.fixture
def bedrock_client(monkeypatch):
    import boto3
    client = Mock()
    create = Mock(return_value=client)
    monkeypatch.setattr(boto3, "client", create)
    monkeypatch.setattr(llm, "_BEDROCK_RETRIES", 2)
    sleeps = []
    monkeypatch.setattr(llm, "_retry_sleep", sleeps.append)
    return client, sleeps


def _response():
    return {"output": {"message": {"content": [{"text": "ok"}]}},
            "usage": {"inputTokens": 12, "outputTokens": 7}}


def _client_error(code="ThrottlingException", message="temporary capacity"):
    from botocore.exceptions import ClientError
    return ClientError({"Error": {"Code": code, "Message": message}}, "Converse")


def test_transient_throttle_retries_same_model_and_preserves_usage(bedrock_client):
    client, sleeps = bedrock_client
    client.converse.side_effect = [_client_error(), _client_error(), _response()]
    result = llm._bedrock_once("system", [{"role": "user", "content": "synthetic"}], "chosen-model")
    assert result == ("ok", {"input_tokens": 12, "output_tokens": 7})
    assert sleeps == [0, 1]
    assert client.converse.call_count == 3
    assert {call.kwargs["modelId"] for call in client.converse.call_args_list} == {"chosen-model"}


def test_exhausted_transient_retries_become_capacity_error(bedrock_client):
    client, sleeps = bedrock_client
    client.converse.side_effect = _client_error()
    with pytest.raises(llm.LLMThrottled):
        llm._bedrock_once("system", [], "chosen-model")
    assert client.converse.call_count == 3
    assert sleeps == [0, 1]


def test_daily_quota_is_not_retried_within_one_model(bedrock_client):
    client, sleeps = bedrock_client
    client.converse.side_effect = _client_error(message="Too many tokens per day")
    with pytest.raises(llm.LLMThrottled):
        llm._bedrock_once("system", [], "chosen-model")
    assert client.converse.call_count == 1
    assert sleeps == []


def test_access_denial_is_not_misclassified_as_capacity(bedrock_client):
    client, sleeps = bedrock_client
    client.converse.side_effect = _client_error("AccessDeniedException", "access not enabled")
    with pytest.raises(llm.LLMError) as caught:
        llm._bedrock_once("system", [], "chosen-model")
    assert not isinstance(caught.value, llm.LLMThrottled)
    assert client.converse.call_count == 1
    assert sleeps == []


class UserCursor:
    """Only the owner-filtered repository statements introduced by reconciliation."""
    def __init__(self):
        self.users = {1: {"id": 1, "autopilot_model": None}, 2: {"id": 2, "autopilot_model": "haiku-4-5"}}
        self.runs = []
        self.result = None
        self.calls = []

    def execute(self, sql, params):
        sql = " ".join(sql.split())
        self.calls.append((sql, params))
        if sql.startswith("SELECT id, email") and sql.endswith("FROM app_users WHERE id=%s"):
            row = self.users.get(params[0])
            fields = re.match(r"SELECT (.+) FROM app_users", sql).group(1).split(", ")
            self.result = {field: row.get(field) for field in fields} if row else None
        elif sql == "UPDATE app_users SET autopilot_model=%s WHERE id=%s":
            model, uid = params
            if uid in self.users:
                self.users[uid]["autopilot_model"] = model
        elif sql == repository.REVIEW_AT_SQL:
            rows = [run for run in self.runs if run["user_id"] == params[0] and run["kind"] == "review"]
            last = max(rows, key=lambda run: run["id"]) if rows else None
            self.result = {"at": last.get("started_at") or last["created_at"]} if last else None
        else:
            raise AssertionError("unexpected repository statement")

    def fetchone(self):
        return self.result


def test_autopilot_model_persists_per_owner_and_default_can_be_restored():
    cur = UserCursor()
    repository.set_autopilot_model(cur, 1, "sonnet-4-5")
    assert repository.get_user(cur, 1)["autopilot_model"] == "sonnet-4-5"
    assert repository.get_user(cur, 2)["autopilot_model"] == "haiku-4-5"
    repository.set_autopilot_model(cur, 1, None)
    assert repository.get_user(cur, 1)["autopilot_model"] is None
    assert repository.get_user(cur, 999) is None
    repository.set_autopilot_model(cur, 999, "opus-4-5")
    assert set(cur.users) == {1, 2}


def test_review_liveness_includes_quiet_reviews_without_cross_user_or_research_leakage():
    cur = UserCursor()
    assert repository.last_review_at(cur, 1) is None
    cur.runs = [{"id": 1, "user_id": 1, "kind": "review", "created_at": datetime(2026, 1, 1)},
                {"id": 2, "user_id": 1, "kind": "review", "created_at": datetime(2026, 1, 2)},
                {"id": 3, "user_id": 1, "kind": "research", "created_at": datetime(2026, 1, 3)},
                {"id": 4, "user_id": 2, "kind": "review", "created_at": datetime(2026, 1, 4)}]
    assert repository.last_review_at(cur, 1) == datetime(2026, 1, 2)
    assert repository.last_review_at(cur, 2) == datetime(2026, 1, 4)
    # Queued at 09:00, ran at 09:40: the check-in is when it ran.
    cur.runs.append({"id": 5, "user_id": 1, "kind": "review", "created_at": datetime(2026, 1, 5, 9),
                     "started_at": datetime(2026, 1, 5, 9, 40)})
    assert repository.last_review_at(cur, 1) == datetime(2026, 1, 5, 9, 40)


@pytest.mark.parametrize("phase", ["research", "validation", "holdout"])
def test_merged_dataset_resolves_partitions_before_off_cursor_loading(monkeypatch, phase):
    owner, cursor, seen = threading.get_ident(), object(), []
    frozen = {key: {"id": index, "frozen_window": (index, index + 1)} for index, key in enumerate(("a", "z"))}

    def freeze(cur, market):
        assert cur is cursor and threading.get_ident() == owner
        seen.append(("freeze", market))
        return frozen[market]

    def load(market, partition):
        assert threading.get_ident() != owner and partition is frozen[market]
        seen.append(("load", market))
        return (market, partition["frozen_window"])

    monkeypatch.setattr(partitions, "ensure_partition", freeze)
    monkeypatch.setattr(partitions, phase + "_dataset", load)
    monkeypatch.setattr(partitions.backtest, "merge_datasets", lambda data, key: {"legs": data, "key": key})
    legs = partitions.merged_partitions(cursor, ["z", "a", "z"])
    assert seen == [("freeze", "a"), ("freeze", "z")]
    with ThreadPoolExecutor(max_workers=1) as pool:
        result = pool.submit(partitions.merged_dataset_from, legs, phase).result(timeout=2)
    assert result == {"legs": [("a", (0, 1)), ("z", (1, 2))], "key": "a+z"}
    assert seen == [("freeze", "a"), ("freeze", "z"), ("load", "a"), ("load", "z")]


@pytest.mark.parametrize("cross", [False, True])
def test_holdout_timeout_does_not_consume_the_one_time_ledger(monkeypatch, cross):
    cursor = object()
    finalist = {"market": "a", "user_id": 1, "spec": {"synthetic": True}}
    partition = {"id": 8, "holdout_from_ts": 100, "holdout_to_ts": 200, "data_fingerprint": "frozen"}
    monkeypatch.setattr(gatekeeper, "_latest_classification", lambda *args: "statistically_supported")
    monkeypatch.setattr(gatekeeper.specmod, "is_cross_contract", lambda spec: cross)
    monkeypatch.setattr(gatekeeper.specmod, "involved_markets", lambda spec: ["a", "z"])
    monkeypatch.setattr(gatekeeper.specmod, "stream_key", lambda spec: "a+z")
    monkeypatch.setattr(gatekeeper.rr, "results_for_experiment", lambda *args: [])
    monkeypatch.setattr(gatekeeper.rr, "get_active_partition", lambda *args: partition)
    monkeypatch.setattr(gatekeeper.partitions, "ensure_merged_partition", lambda *args: partition)
    monkeypatch.setattr(gatekeeper.partitions, "merged_partitions", lambda *args: [("a", partition), ("z", partition)])
    monkeypatch.setattr(gatekeeper.rr, "ensure_holdout_ledger", lambda *args: {"id": 2, "consumed": 0, "evaluations_used": 0, "max_evaluations": 3})
    monkeypatch.setattr(gatekeeper.rr, "holdout_evaluations_overlapping", lambda *args: 0)
    spend, append = Mock(), Mock()
    monkeypatch.setattr(gatekeeper.rr, "record_holdout_use", spend)
    monkeypatch.setattr(gatekeeper.rr, "append_result", append)
    load = Mock(side_effect=AssertionError("a timeout must not trigger an inline reload"))
    monkeypatch.setattr(gatekeeper.partitions, "holdout_dataset", load)
    monkeypatch.setattr(gatekeeper.partitions, "merged_dataset_from", load)

    def timed_out(loader):
        assert callable(loader)
        raise TimeoutError("synthetic dataset timeout")

    with pytest.raises(TimeoutError):
        gatekeeper.judge_holdout(cursor, 1, finalist, run_load=timed_out)
    spend.assert_not_called()
    append.assert_not_called()
    load.assert_not_called()


@pytest.mark.parametrize("override,expected", [(None, "20"), ("35", "35")])
def test_free_credit_default_matches_production_without_changing_explicit_configuration(monkeypatch, override, expected):
    if override is None:
        monkeypatch.delenv("TAU_FREE_CREDITS", raising=False)
    else:
        monkeypatch.setenv("TAU_FREE_CREDITS", override)
    path = Path(billing.__file__)
    spec = importlib.util.spec_from_file_location("billing_reconciliation_defaults", path)
    instance = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(instance)
    assert instance.FREE_BONUS == Decimal(expected)
