#!/usr/bin/env python3
"""Offline P0 contract: never automatically recover or resend any NBA slot."""
from pathlib import Path
from nba_delivery_health import exact_fixed_run_slot
def test():
    r={"event":"schedule","display_title":"NBA full report | slot=0 7 * * * | date=auto"}
    assert not exact_fixed_run_slot(r,"1600","2026-11-07")
    assert exact_fixed_run_slot({**r,"display_title":"NBA full report | slot=0 8 * * * | date=auto"},"1600","2026-11-07")
    recovery=Path(__file__).with_name("nba_delivery_recovery.py").read_text()
    assert "urllib.request" not in recovery and "dispatches" not in recovery
    workflow=Path(".github/workflows/nba-delivery-health-watchdog.yml").read_text()
    assert "nba_delivery_recovery.py" not in workflow and "--send" not in workflow
    print("NBA_P0_NO_COMPENSATION_TEST_PASS")
if __name__=="__main__":test()
