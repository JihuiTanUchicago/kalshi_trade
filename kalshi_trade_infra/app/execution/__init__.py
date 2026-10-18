"""Execution-path hardening (EXECUTION_RISK_HARDENING P1).

Home for the controls that sit on the REAL-order path and are shared by the live
(``app.engine.live_kernel_factory``) and demo (``app.kalshi_dev_exec.demo_kernel_factory``)
submitters. Keeping them here — not in the per-venue factories — is what stops the two
paths drifting apart on a money/safety control.
"""
from app.execution.guard import guarded_submitter
from app.execution.latency import timed_submitter

__all__ = ["guarded_submitter", "timed_submitter"]
