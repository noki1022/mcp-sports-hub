#!/usr/bin/env python3
"""Production schedule and immutability guard for both sports.

One twelve-hour analysis window, 12:00–23:00 Beijing; 21:00 immutable
graded forecast; no other automatic pregame PushPlus sender.
Existing independent result validation and long-term backups are retained.
"""
from pathlib import Path
import tomllib
import yaml

ROOT=Path(__file__).resolve().parents[1]
WF=ROOT/".github/workflows"
HOURS=[f"0 {hour} * * *" for hour in range(4,16)]
PRODUCTION={
    "titan007-three-analysis.yml":HOURS,
    "football-007-live-capture.yml":HOURS,
}
FOOTBALL_REVIEW_PUSH="football-review-push-1300.yml"
QUIET_ALLOW={
    "sports-per-match-finalizer.yml",
    "sports-integrity-and-leakage-gates.yml",
    "nba-per-match-final-review-audit.yml",
    "sports-data-lifecycle.yml",
    "sports-verified-results.yml",
    "nba-two-market-nightly-2200.yml",
    "odds-results-settlement.yml",
    "nba-archive-capacity-watch.yml",
    "nba-raw-vault-backup.yml",
    "nba-injury-live-roster-feature-freeze.yml",
}
DISABLED={
    "nba-priority-2130.yml","nba-priority-0630.yml",
    "nba-silent-overnight-hourly.yml","nba-injury-change-watch.yml",
    "nba-dual-final-2130-score.yml","nba-full-chain-e2e.yml",
}

def load(name):
    path=WF/name
    doc=yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(doc,dict),("BAD_YAML",name)
    for job,config in (doc.get("jobs") or {}).items():
        for step in config.get("steps") or []:
            assert ("run" in step) != ("uses" in step),(name,job,"AMBIGUOUS_ACTION")
    return doc

def crons(name):
    d=load(name)
    events=d.get("on",d.get(True,{}))
    return [x["cron"] for x in (events or {}).get("schedule",[])]

def main():
    files={p.name for p in WF.glob("*.yml")}
    assert set(PRODUCTION)|QUIET_ALLOW|DISABLED|{FOOTBALL_REVIEW_PUSH} <= files
    scheduled={name for name in files if crons(name)}
    unexpected=scheduled-(set(PRODUCTION)|QUIET_ALLOW|{FOOTBALL_REVIEW_PUSH})
    assert not unexpected,("EXTRA_SCHEDULED_WORKFLOWS",sorted(unexpected))
    for name,expected in PRODUCTION.items():
        assert crons(name)==expected,("NOT_EXACT_TWELVE_SLOTS",name,crons(name))
    assert crons(FOOTBALL_REVIEW_PUSH)==["0 5 * * *"],"FOOTBALL_REVIEW_MUST_RUN_AT_BEIJING_1300"
    postgame={
        FOOTBALL_REVIEW_PUSH: "0 5 * * *",
        "nba-two-market-nightly-2200.yml": "0 7 * * *",
        "sports-per-match-finalizer.yml": "25 * * * *",
        "sports-verified-results.yml": "50 * * * *",
    }
    for name, expected in postgame.items():
        assert crons(name)==[expected],("INCORRECT_POSTGAME_SLOT",name)
        workflow=load(name)
        events=workflow.get("on",workflow.get(True))
        assert "cloudflare_slot_utc" in events["workflow_dispatch"]["inputs"],name
    nba_review_gate=next(s["run"] for s in load("nba-two-market-nightly-2200.yml")["jobs"]["settle-and-notify"]["steps"]
                         if s.get("name")=="Check last frozen game has official Final before review")
    assert 'day="$(TZ=Asia/Shanghai date +%F)"' in nba_review_gate, "NBA_REVIEW_GAME_DAY_MUST_MATCH_SEND_DAY"
    review_workflow=load(FOOTBALL_REVIEW_PUSH)
    assert set(review_workflow.get("on",review_workflow.get(True)))=={"schedule","pull_request","workflow_dispatch"}
    for name in DISABLED:
        assert not crons(name),("OLD_PREMATCH_SCHEDULE_STILL_ACTIVE",name)
    cloud=tomllib.loads((ROOT/"scheduler/wrangler.toml").read_text())
    assert cloud["triggers"]["crons"]==["0 4-15 * * *", "25,50 * * * *"],"CLOUDFLARE_HAS_EXTRA_CRON"
    worker=(ROOT/"scheduler/worker.mjs").read_text()
    assert "h>=12&&h<=23&&m===0" in worker
    assert "EXACT_SLOT" in worker and "NO_RETRY" in worker
    basket=(WF/"titan007-three-analysis.yml").read_text()
    football=(WF/"football-007-live-capture.yml").read_text()
    assert "nba_five_market_forecast.json" in basket
    assert "nba_fixed_slot_gate.py" in basket
    assert "reports/daily/" in basket
    assert "football_007_live_capture.py" in football
    assert "--jc-sale-day" in football
    assert "football_jc_final_2100.json" in football
    assert "football-jc-final-2100-" in football
    assert "archive-football-2100-final" in football
    assert "football-daytime-push:" in football
    assert "football-final-and-morning-push:" not in football
    assert "30 13 * * *" not in football and "30 22 * * *" not in football
    assert "FOOTBALL_PUSHPLUS_TOKEN" not in str(load("football-007-live-capture.yml")["jobs"]["live-football"])
    assert "FOOTBALL_PUSHPLUS_TOKEN" not in str(load("football-007-live-capture.yml")["jobs"]["archive-football-raw-release"])
    assert "archive-football-raw-release" in str(load("football-007-live-capture.yml")["jobs"]["football-daytime-push"]["needs"])
    registry=(ROOT/"analysis/sport_match_final_registry.py").read_text()
    review=(ROOT/"analysis/nba_final_review_gate.py").read_text()
    assert 'r["planned_slot_beijing"]=="2100"' in registry
    assert '"2100"/"nba_five_market_forecast.json"' in review
    assert '"2130","2100"' not in review
    for forbidden in ("scripts/nba_delivery_recovery.py","scripts/nba_schedule_fallback_push.py",
                      ".github/workflows/pushplus-compact-resend.yml"):
        assert not (ROOT/forbidden).exists(),forbidden
    print("SCHEDULE_12_HOURS_FOOTBALL_007_WEEKDAY_AND_2100_SCORE_GUARD_PASS")

if __name__=="__main__":
    main()
