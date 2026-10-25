"""The event-driven autopilot loop: a research run ending immediately enqueues a 'review' so the
co-pilot acts on the fresh results, bounded by the same dedup / min-interval / billing gate the
heartbeat uses so it stays continuous without becoming a runaway."""
from contextlib import contextmanager
from unittest.mock import patch

from app import worker


def _count_runs(active=None, recent=None):
    """Fake repo.count_runs: `active` maps (uid,kind)->count for active_only lookups, `recent` maps
    (uid,kind)->count for the since= min-interval lookup; everything else is 0."""
    active, recent = active or {}, recent or {}
    def count_runs(cur, uid, kind, since=None, active_only=False):
        if active_only:
            return active.get((uid, kind), 0)
        if since is not None:
            return recent.get((uid, kind), 0)
        return 0
    return count_runs


@contextmanager
def _fake_txn(conn):
    yield None  # cur is unused: the repo fns it would touch are patched in each test


def _run_hook(uid, *, autopilot=True, ready=True, active=None, recent=None):
    """Drive enqueue_review_after_research with everything it depends on faked; return the list of
    (uid, kind) pairs that got create_run'd."""
    created = []
    with patch.object(worker.repo, "transaction", _fake_txn), \
         patch.object(worker.repo, "autopilot_on", return_value=autopilot), \
         patch.object(worker.repo, "count_runs", side_effect=_count_runs(active, recent)), \
         patch.object(worker.billing, "is_ready", return_value=ready), \
         patch.object(worker.repo, "create_run",
                      side_effect=lambda cur, uid, kind, **kw: created.append((uid, kind))):
        worker.enqueue_review_after_research(conn=None, user_id=uid)
    return created


def test_research_completion_enqueues_a_review():
    assert _run_hook(1) == [(1, "review")]


def test_dedup_blocks_when_a_review_is_already_in_flight():
    assert _run_hook(1, active={(1, "review"): 1}) == []


def test_dedup_blocks_when_a_chat_is_already_in_flight():
    assert _run_hook(1, active={(1, "chat"): 1}) == []


def test_min_interval_floor_blocks_a_too_soon_re_enqueue():
    # A review created within APP_AUTOPILOT_MIN_REVIEW_SECONDS blocks the next one.
    assert _run_hook(1, recent={(1, "review"): 1}) == []


def test_autopilot_off_user_gets_none():
    assert _run_hook(1, autopilot=False) == []


def test_non_billing_ready_user_gets_none():
    assert _run_hook(1, ready=False) == []


def test_hook_swallows_errors_without_raising():
    # A failing enqueue must never kill the worker loop or lose the committed research result.
    with patch.object(worker.repo, "transaction", _fake_txn), \
         patch.object(worker.repo, "autopilot_on", side_effect=RuntimeError("boom")):
        worker.enqueue_review_after_research(conn=None, user_id=1)  # does not raise


if __name__ == "__main__":
    test_research_completion_enqueues_a_review()
    test_dedup_blocks_when_a_review_is_already_in_flight()
    test_dedup_blocks_when_a_chat_is_already_in_flight()
    test_min_interval_floor_blocks_a_too_soon_re_enqueue()
    test_autopilot_off_user_gets_none()
    test_non_billing_ready_user_gets_none()
    test_hook_swallows_errors_without_raising()
    print("ok")


def _run_switch_on(uid, *, ready=True, active=None, recent=None):
    """Drive enqueue_review_on_switch_on with its repo/billing calls faked; return created runs."""
    created = []
    with patch.object(worker.repo, "count_runs", side_effect=_count_runs(active, recent)), \
         patch.object(worker.billing, "is_ready", return_value=ready), \
         patch.object(worker.repo, "create_run",
                      side_effect=lambda cur, uid, kind, **kw: created.append((uid, kind))):
        worker.enqueue_review_on_switch_on(None, uid)
    return created


def test_switching_autopilot_on_starts_a_review_now():
    assert _run_switch_on(5) == [(5, "review")]


def test_switch_on_never_stacks_on_a_recent_or_running_review_or_unbilled_user():
    assert _run_switch_on(5, recent={(5, "review"): 1}) == []
    assert _run_switch_on(5, active={(5, "review"): 1}) == []
    assert _run_switch_on(5, ready=False) == []
