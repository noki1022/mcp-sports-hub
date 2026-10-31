#!/usr/bin/env python3
"""Evidence-based fixture recovery when 007 delivers a partial or failed response.

Never invent 007 IDs, odds, or current quotations. Retain every current verified
row and recover missing fixture rows only from an older, timestamped, identity-
verified actual archive. The official slate determines the cohort dynamically.
Every restored row is visibly labeled archived/non-live. No network required.
"""
from __future__ import annotations

import argparse
import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from nba_noon_slate import official_identity, market_identity, aware


def utc(value):
    stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        raise ValueError("RECOVERY_TIMESTAMP_MISSING_ZONE")
    return stamp.astimezone(timezone.utc)


def valid_row(row, fixture, timestamp, first_id=None):
    """Strict NBA ID, home/away code, pre-tip capture and verified Beijing time."""
    from titan007_ev_analysis import NAMES
    if not row or row.get("league") != "NBA":
        return False
    try:
        if str(row.get("nba_game_id")) != str(fixture["nba_game_id"]):
            return False
        if not str(row.get("game_id", "")).isdigit():
            return False
        if first_id is not None and str(first_id) != str(row["game_id"]):
            return False
        home = NAMES.get(row.get("home_team")) or ()
        away = NAMES.get(row.get("away_team")) or ()
        if not home or not away or home[0] != fixture["home"] or away[0] != fixture["away"]:
            return False
        tip = utc(fixture["utc_tip"])
        if utc(row["start_time_beijing"]) != tip or utc(row["tipoff_utc"]) != tip:
            return False
        if utc(timestamp) >= tip:
            return False
        if row.get("display_date") != fixture["beijing_date"]:
            return False
        return True
    except (KeyError, ValueError, TypeError):
        return False


def archive_candidates(root, day):
    for path in (root / "reports" / "daily" / day).glob("*/*joined.json"):
        if path.name not in ("titan007_three_joined.json", "titan007_priority_joined.json"):
            continue
        try:
            obj = json.loads(path.read_text(encoding="utf-8"))
            captured = utc(obj["captured_at_utc"])
            if obj.get("requested_display_date") == day:
                yield captured, path, obj
        except (ValueError, OSError, KeyError, TypeError):
            continue


def recover(current, root, *, target=None, now=None):
    root = Path(root)
    day = target or (current or {}).get("requested_display_date")
    if not day:
        raise ValueError("RECOVERY_TARGET_REQUIRED")
    clock = utc(now or (current or {}).get("captured_at_utc") or datetime.now(timezone.utc).isoformat())
    cohort = root / "reports" / "noon-cohorts" / day / "1200.json"
    if not cohort.is_file():
        raise RuntimeError("RECOVERY_NO_VERIFIED_OFFICIAL_COHORT")
    locked = json.loads(cohort.read_text(encoding="utf-8"))
    if locked.get("target_beijing_date") != day:
        raise RuntimeError("RECOVERY_COHORT_DAY_MISMATCH")
    official = locked.get("official_games") or {}
    if not official or len(official) != locked.get("official_count"):
        raise RuntimeError("RECOVERY_INVALID_OFFICIAL_COHORT")

    if current is not None:
        if current.get("requested_display_date") != day:
            raise RuntimeError("RECOVERY_LIVE_DATE_MISMATCH")
        if official_identity(current) != official:
            raise RuntimeError("RECOVERY_OFFICIAL_SCHEDULE_CHANGED")
        market_identity(current, official)  # Existing P0 identity and 007 ID checks.
    # No source failures are required: a bookmaker can temporarily close just
    # one matchup without an HTTP error, while earlier pre-tip odds are real.
    seen = {}
    for g in (current or {}).get("nba_cba_games", []):
        fid = str(g["nba_game_id"])
        if not valid_row(g, official[fid], (current or {})["captured_at_utc"],
                         (locked.get("first_available_007") or {}).get(fid)):
            raise RuntimeError("RECOVERY_LIVE_ROW_IDENTITY_OR_TIME_INVALID_" + fid)
        item = deepcopy(g)
        item["quote_freshness"] = "CURRENT_CAPTURE"
        item["quote_captured_at_utc"] = current["captured_at_utc"]
        seen[fid] = item
    original_count = len(seen)
    recovered = []
    candidates = sorted(archive_candidates(root, day), key=lambda x: x[0], reverse=True)
    for capture, path, past in candidates:
        if capture >= clock:
            continue
        try:
            if official_identity(past) != official:
                continue
            market_identity(past, official)
        except (ValueError, TypeError, KeyError):
            continue
        for g in past.get("nba_cba_games", []):
            fid = str(g.get("nba_game_id"))
            if fid in seen or fid not in official:
                continue
            if not valid_row(g, official[fid], past["captured_at_utc"],
                             (locked.get("first_available_007") or {}).get(fid)):
                continue
            item = deepcopy(g)
            item["quote_freshness"] = "ARCHIVED_PRIOR_NOT_LIVE"
            item["quote_captured_at_utc"] = past["captured_at_utc"]
            item["quote_archive_path"] = str(path.relative_to(root))
            seen[fid] = item
            recovered.append({"nba_game_id":fid, "007_game_id":str(item["game_id"]),
                              "observed_at_utc":past["captured_at_utc"],
                              "archive":str(path.relative_to(root))})
        if len(seen) == len(official):
            break
    if current is None:
        # Only an actual verified prior capture can bootstrap a fully failed
        # source fetch. Preserve real historical fixture/quote timestamps.
        source = next((past for cap, _, past in candidates if cap < clock
                       and (lambda p: p.get("requested_display_date") == day)(past)), None)
        if source is None:
            raise RuntimeError("RECOVERY_NO_PREVIOUS_VERIFIED_CAPTURE")
        base = deepcopy(source)
        base["captured_at_utc"] = clock.isoformat()
        base["source_query_errors"] = [{"source":"007","error":"ALL_LIVE_ATTEMPTS_FAILED"}]
    else:
        base = deepcopy(current)
    ordered = sorted(seen.values(), key=lambda g: (utc(g["start_time_beijing"]),str(g["game_id"])))
    if not ordered:
        raise RuntimeError("RECOVERY_NO_VERIFIED_NBA_IDENTITY")
    base["nba_cba_games"] = ordered
    base["nba_cba_joined_for_date"] = len(ordered)
    base["verified_fixture_ids_for_date"] = len(ordered)
    base["official_schedule_count"] = len(official)
    base["markets_joined_for_date"] = sum(any(
        (g.get("markets",{}).get(k,{}).get("current") or {}).get("line") is not None
        for k in ("full_spread","full_total")) for g in ordered)
    base["nba_markets_missing"] = len(official)-base["markets_joined_for_date"]
    # Keep unmatched reasons only for still-missing official identities/markets.
    coverage = {str(g["nba_game_id"]) for g in ordered if any(
        (g.get("markets",{}).get(k,{}).get("current") or {}).get("line") is not None
        for k in ("full_spread","full_total"))}
    base["unmatched_nba_fixtures"] = [
        {"nba_game_id":fid,"home":f["home"],"away":f["away"],"reason":"NO_VERIFIED_CURRENT_OR_ARCHIVED_MARKET"}
        for fid,f in official.items() if fid not in coverage]
    base["report_quality"] = ("RECOVERED_ARCHIVED_QUOTES_NOT_LIVE" if recovered
                              else base.get("report_quality","NO_RECOVERY_NEEDED"))
    base["quote_recovery"] = {"schema_version":"verified-007-archive-recovery-v1",
        "official_games":len(official),"current_verified_games":original_count,
        "recovered_games":len(recovered),"still_unmatched":len(official)-len(ordered),
        "archived_quotes_are_not_current":bool(recovered),"rows":recovered}
    return base


def self_test():
    from tempfile import TemporaryDirectory
    from datetime import timedelta
    from zoneinfo import ZoneInfo
    import sys
    BJ=ZoneInfo("Asia/Shanghai")
    day="2026-11-01"
    now=datetime.fromisoformat("2026-10-31T23:00:00+08:00")
    teams=[("401a","7281","UTA","POR","犹他爵士","波特兰开拓者",3),
           ("401b","7282","CHA","PHI","夏洛特黄蜂","费城76人",6),
           ("401c","7283","HOU","OKC","休斯顿火箭","俄克拉荷马城雷霆",8)]
    fixtures=[];rows=[]
    for fid,gid,h,a,hn,an,hour in teams:
        tip=datetime.fromisoformat(f"{day}T{hour:02}:00:00+08:00")
        fixtures.append({"nba_game_id":fid,"home":h,"away":a,
                         "utc_tip":tip.astimezone(timezone.utc).isoformat(),
                         "beijing_date":day})
        rows.append({"game_id":gid,"nba_game_id":fid,"league":"NBA",
            "home_team":hn,"away_team":an,"display_date":day,
            "display_clock":f"{hour:02}:00",
            "tipoff_utc":tip.astimezone(timezone.utc).isoformat(),
            "start_time_beijing":tip.isoformat(),
            "markets":{"full_spread":{"current":{"line":-2.5}},
                       "full_total":{"current":{"line":221.5}}}})
    prior={"requested_display_date":day,"captured_at_utc":"2026-10-31T21:30:00+08:00",
           "official_schedule_count":len(fixtures),"upcoming_nba_games":fixtures,
           "nba_cba_games":rows}
    current={**prior,"captured_at_utc":now.isoformat(),"nba_cba_games":rows[:1],
             "source_query_errors":[{"source":"SCOREBOARD","error":"URLError"}]}
    with TemporaryDirectory() as tmp:
        root=Path(tmp)
        frozen=root/"reports"/"noon-cohorts"/day/"1200.json"
        frozen.parent.mkdir(parents=True)
        frozen.write_text(json.dumps({"target_beijing_date":day,"official_games":
            {f["nba_game_id"]:f for f in fixtures},"official_count":len(fixtures),
            "first_available_007":{g["nba_game_id"]:g["game_id"] for g in rows}}))
        archive=root/"reports"/"daily"/day/"2130"/"titan007_priority_joined.json"
        archive.parent.mkdir(parents=True)
        archive.write_text(json.dumps(prior))
        result=recover(current,root)
        assert len(result["nba_cba_games"])==len(fixtures)
        assert result["quote_recovery"]["recovered_games"]==len(fixtures)-1
        assert result["nba_cba_games"][0]["quote_freshness"]=="CURRENT_CAPTURE"
        assert all(g["quote_freshness"]=="ARCHIVED_PRIOR_NOT_LIVE" for g in result["nba_cba_games"][1:])
        assert len(recover(None,root,target=day,now=now.isoformat())["nba_cba_games"])==len(fixtures)
        bad=json.loads(json.dumps(prior))
        bad["nba_cba_games"][1]["game_id"]="728999"
        archive.write_text(json.dumps(bad))
        assert recover(current,root)["quote_recovery"]["recovered_games"]==0
        archive.write_text(json.dumps(prior))
        bad_current=json.loads(json.dumps(current))
        bad_current["nba_cba_games"][0]["home_team"]="夏洛特黄蜂"
        try:
            recover(bad_current,root)
        except RuntimeError:
            pass
        else:
            raise AssertionError("CROSS_TEAM_IDENTITY_NOT_BLOCKED")
        assert recover(current,root,now=(now-timedelta(hours=2)).isoformat())["quote_recovery"]["recovered_games"]==0
    print("NBA_DYNAMIC_FULL_SLATE_ARCHIVE_RECOVERY_PASS")


def cli():
    p=argparse.ArgumentParser()
    p.add_argument("--joined",default="")
    p.add_argument("--target",default="")
    p.add_argument("--out",default="")
    p.add_argument("--root",default=".")
    p.add_argument("--self-test",action="store_true")
    a=p.parse_args()
    if a.self_test:
        return self_test()
    if not a.out or (not a.joined and not a.target):
        p.error("OUT_AND_JOINED_OR_TARGET_REQUIRED")
    current=json.loads(Path(a.joined).read_text(encoding="utf-8")) if a.joined else None
    result=recover(current,Path(a.root),target=a.target or None)
    Path(a.out).write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("NBA_EVIDENCE_RECOVERY",json.dumps(result["quote_recovery"],ensure_ascii=False))


if __name__=="__main__":
    cli()
