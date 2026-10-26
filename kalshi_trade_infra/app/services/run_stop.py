"""Why a finished research session stopped, from what the run already stores.

A "run until I stop it" session that used up the credits ends `succeeded`, like one that ran out of
ideas, so the research list read "Done" for both. Nothing about how runs execute or are recorded
changes here: the reason is read from the run's status, its run_forever flag, and whether its log
holds the agent's out-of-credits step (agent.run_research logs repo.OUT_OF_CREDITS_STEP when the
balance is spent, then finishes the run `succeeded`; repo.list_runs reads it as `out_of_credits`).

    credits      it stopped because the credits ran out (a run-until-stopped session)
    user         you cancelled it
    error        it failed on an error
    interrupted  its worker stopped and it couldn't be resumed (the reaper's `stopped`)
    no_data      the market had nothing to research yet (a NoData `stopped`)
    limit        it tested the number of ideas it was set to
    complete     a run-until-stopped session found nothing new to try
    None         still queued, running or paused
"""
from __future__ import annotations

from typing import Dict, Optional

ACTIVE = ("queued", "running", "paused")


def stop_reason(run: Dict) -> Optional[str]:
    """One of the codes above for a run row carrying status, run_forever, error and out_of_credits."""
    status = run.get("status")
    if status in ACTIVE or not status:
        return None
    if status == "cancelled":
        return "user"
    if status == "failed":
        return "error"
    if status == "stopped":
        return "interrupted" if "interrupted" in (run.get("error") or "").lower() else "no_data"
    if status == "succeeded":
        if run.get("out_of_credits"):
            return "credits"
        return "complete" if run.get("run_forever") else "limit"
    return None
