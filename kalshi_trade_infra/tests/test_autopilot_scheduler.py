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


if __name__ == "__main__":
    test_due_skips_users_with_an_inflight_copilot_run()
    test_all_free_users_are_due()
    test_no_autopilot_users_means_nothing_due()
    print("ok")
