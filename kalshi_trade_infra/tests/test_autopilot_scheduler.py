"""The autopilot heartbeat enqueues a 'review' run for each autopilot-on user that has no
co-pilot run already in flight — the only thing that makes the co-pilot act on its own."""
from unittest.mock import patch

from app import worker


def _counts(active_by_user):
    """Fake repo.count_runs: active_by_user maps (uid, kind) -> count for active_only lookups."""
    def count_runs(cur, uid, kind, since=None, active_only=False):
        return active_by_user.get((uid, kind), 0) if active_only else 0
    return count_runs


def test_due_skips_users_with_an_inflight_copilot_run():
    with patch.object(worker.repo, "autopilot_user_ids", return_value=[1, 2, 3]), \
         patch.object(worker.repo, "count_runs",
                      side_effect=_counts({(2, "review"): 1, (3, "chat"): 1})):
        # user 1 is free; user 2 has a review running; user 3 has a chat running
        assert worker.due_autopilot_users(cur=None) == [1]


def test_all_free_users_are_due():
    with patch.object(worker.repo, "autopilot_user_ids", return_value=[7, 9]), \
         patch.object(worker.repo, "count_runs", side_effect=_counts({})):
        assert worker.due_autopilot_users(cur=None) == [7, 9]


def test_no_autopilot_users_means_nothing_due():
    with patch.object(worker.repo, "autopilot_user_ids", return_value=[]), \
         patch.object(worker.repo, "count_runs", side_effect=_counts({})):
        assert worker.due_autopilot_users(cur=None) == []


def _idle_counts(research_active, recent_review):
    def count_runs(cur, uid, kind, since=None, active_only=False):
        if kind == "research" and active_only:
            return research_active
        if kind == "review" and since is not None and not active_only:
            # MIN_REVIEW_SECONDS window (90s) sees nothing; the idle window sees the last review
            return recent_review if (worker.repo.now_utc() - since).total_seconds() > 600 else 0
        return 0
    return count_runs


def test_saturated_research_and_nothing_deployed_spaces_out_heartbeat_reviews():
    with patch.object(worker.repo, "autopilot_user_ids", return_value=[2]), \
         patch.object(worker.repo, "count_runs", side_effect=_idle_counts(2, 1)), \
         patch.object(worker.repo, "list_deployments", return_value=[{"status": "stopped"}]):
        assert worker.due_autopilot_users(cur=None) == []
    # No review in the idle window yet -> still due.
    with patch.object(worker.repo, "autopilot_user_ids", return_value=[2]), \
         patch.object(worker.repo, "count_runs", side_effect=_idle_counts(2, 0)), \
         patch.object(worker.repo, "list_deployments", return_value=[]):
        assert worker.due_autopilot_users(cur=None) == [2]


def test_a_free_research_slot_or_a_live_deployment_keeps_the_normal_cadence():
    with patch.object(worker.repo, "autopilot_user_ids", return_value=[2]), \
         patch.object(worker.repo, "count_runs", side_effect=_idle_counts(1, 1)):
        assert worker.due_autopilot_users(cur=None) == [2]
    with patch.object(worker.repo, "autopilot_user_ids", return_value=[2]), \
         patch.object(worker.repo, "count_runs", side_effect=_idle_counts(2, 1)), \
         patch.object(worker.repo, "list_deployments", return_value=[{"status": "running"}]):
        assert worker.due_autopilot_users(cur=None) == [2]
    with patch.object(worker.repo, "autopilot_user_ids", return_value=[2]), \
         patch.object(worker.repo, "count_runs", side_effect=_idle_counts(2, 1)), \
         patch.object(worker.repo, "list_deployments", return_value=[{"status": "paused"}]):
        assert worker.due_autopilot_users(cur=None) == []  # a guard-paused deployment trades nothing


if __name__ == "__main__":
    test_due_skips_users_with_an_inflight_copilot_run()
    test_all_free_users_are_due()
    test_no_autopilot_users_means_nothing_due()
    print("ok")


def test_heartbeat_skips_a_user_an_event_review_just_covered():
    def count_runs(cur, uid, kind, since=None, active_only=False):
        if kind == "review" and since is not None and not active_only:
            window = (worker.repo.now_utc() - since).total_seconds()
            return 1 if worker.MIN_REVIEW_SECONDS < window <= worker.HEARTBEAT_RECENT_SECONDS else 0
        return 0
    with patch.object(worker.repo, "autopilot_user_ids", return_value=[2]), \
         patch.object(worker.repo, "count_runs", side_effect=count_runs), \
         patch.object(worker.repo, "list_deployments", return_value=[]):
        assert worker.due_autopilot_users(cur=None) == []
