"""Operator-started paper worker; never creates an app automation or daemon."""
from __future__ import annotations

from datetime import timedelta
import time

from .common import GateError,timestamp,utcnow
from .data import Dataset
from .paper import PaperController


def watch(controller: PaperController, directory: str, interval: int = 30, iterations: int = 0) -> dict:
    if not 5<=interval<=60 or iterations<0:
        raise GateError("Paper polling interval must be 5–60 seconds; iterations must be nonnegative")
    count,cycles = 0,0
    try:
        while iterations==0 or count<iterations:
            count += 1
            try:
                data = None
                try:
                    data = Dataset(directory)
                    controller.refresh_actions(data)
                except GateError as exc:
                    controller.store.event(None,"paper_input_gate",{"reason":str(exc)[:300]})
                    controller.pause("Fresh paper inputs unavailable or unqualified")
                    data = None
                controller.poll()
                pending = controller.store.control("paper_pending_release")
                if pending and not controller.store.control("paper_pause",False):
                    controller.activate(pending)
                    controller.store.set_control("paper_pending_release",None)
                if data is None:
                    if iterations==0 or count<iterations: time.sleep(interval)
                    continue
                upcoming = data.manifest.get("next_session")
                if upcoming:
                    current,opening = timestamp(utcnow()),timestamp(upcoming["open_at"])
                    if opening-timedelta(minutes=60)<=current<=opening-timedelta(minutes=3):
                        controller.cycle(data)
                        cycles += 1
            except GateError as exc:
                controller.store.event(None,"paper_worker_gate",{"reason":str(exc)[:300]})
                controller.pause("Paper worker reconciliation/risk gate failed")
            if iterations==0 or count<iterations: time.sleep(interval)
    except KeyboardInterrupt:
        controller.pause("Operator interrupted paper worker")
    return {"polls":count,"eligible_cycles":cycles,"paused":controller.store.control("paper_pause",False)}
