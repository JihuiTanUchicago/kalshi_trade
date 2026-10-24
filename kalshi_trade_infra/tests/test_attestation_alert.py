"""The attestation warning must reach the operator before orders start 403ing.

On 2026-10-24 the alerter had been off while an expired attestation was
renewed; it came back to -9 days in its state and 0.4 days live, and the old
crossing-only rule said nothing.
"""
import data_pipeline.live_alerter as la


def test_entering_the_window_warns():
    assert "expires in 1.5 days" in la.attestation_alert(1.5, 3.0)


def test_first_run_inside_the_window_warns():
    assert la.attestation_alert(1.5, None)


def test_standing_inside_the_window_is_quiet():
    assert la.attestation_alert(1.4, 1.5) is None


def test_lapsing_warns_again_as_expired():
    assert "EXPIRED" in la.attestation_alert(-0.01, 0.002)


def test_staying_expired_is_quiet():
    assert la.attestation_alert(-2.0, -1.9) is None


def test_renewal_into_a_short_window_warns():
    assert "expires in 0.4 days" in la.attestation_alert(0.4, -9.17)


def test_outside_the_window_is_quiet():
    assert la.attestation_alert(5.0, 0.5) is None


def test_unreadable_is_quiet():
    assert la.attestation_alert(None, 0.5) is None
