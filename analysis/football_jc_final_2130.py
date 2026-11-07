#!/usr/bin/env python3
"""21:00 canonical football JC frozen forecast; no future-slot replacement.

No shadow forecast. Uses 007 Asian-integrated football report only. Scheduled
UTC 13:00 slot means Beijing 21:00. Freeze is an immutable payload intended
for a create-only GitHub Release asset; it never uses a 06:30 snapshot to grade.
Actual capture timestamp is retained (cron is not guaranteed exact).
"""
from __future__ import annotations
import argparse
from datetime import datetime,timedelta,timezone
import hashlib, json, math, statistics
from pathlib import Path
from zoneinfo import ZoneInfo
from typing import Any

BJ=ZoneInfo("Asia/Shanghai")
VERSION="football-jc-single-final-2100-v1"
import football_forecast_contract as contract
KEYS=("had","hhad","ttg")
LABELS={"had":"竞彩胜平负","hhad":"竞彩让球胜平负","ttg":"竞彩总进球数"}
MAX_DELAY=120 # scheduled 21:00 source window; never relabel a late capture as on-time

def as_dt(s):
    d=datetime.fromisoformat(str(s).replace("Z","+00:00"))
    if d.tzinfo is None:raise ValueError("TIMESTAMP_MUST_INCLUDE_TIMEZONE")
    return d.astimezone(timezone.utc)

def sha(obj):
    return hashlib.sha256(json.dumps(obj,ensure_ascii=False,sort_keys=True).encode()).hexdigest()

def source_check(snapshot,forecast):
    if snapshot.get("schema_version")!="football-jc-007-v1":
        raise ValueError("INVALID_FOOTBALL_SOURCE_SCHEMA")
    if not contract.compatible(forecast):
        raise ValueError("ONLY_INTEGRATED_FOOTBALL_JC_MODEL_PERMITTED")
    if forecast.get("source_sha256")!=sha(snapshot):
        raise ValueError("FORECAST_NOT_FROM_007_SNAPSHOT")
    captured=as_dt(snapshot["captured_at_utc"])
    if as_dt(forecast["captured_at_utc"])!=captured:
        raise ValueError("FORECAST_CAPTURE_MISMATCH")
    generated=as_dt(forecast["generated_at_utc"])
    if generated<captured:
        raise ValueError("FORECAST_PRECEDES_CAPTURE")
    originals=snapshot.get("games")
    forecasts=forecast.get("games")
    if not isinstance(originals,list) or not isinstance(forecasts,list) or len(originals)!=len(forecasts):
        raise ValueError("SNAPSHOT_AND_FORECAST_GAME_COUNT_MISMATCH")
    seen=set()
    for a,b in zip(originals,forecasts):
        mid=str(a.get("match_id") or "")
        if not mid.isdecimal() or mid in seen:
            raise ValueError("DUPLICATE_OR_INVALID_007_MATCH_ID")
        seen.add(mid)
        if mid!=str(b.get("match_id")) or a.get("jc_number")!=b.get("jc_number"):
            raise ValueError("FORECAST_MATCH_ID_AND_JC_NUMBER_MISMATCH")
        if any(a.get(k)!=b.get(k) for k in ("home_team","away_team")):
            raise ValueError("HOME_AWAY_TEAM_CHANGED")
        tip=as_dt(a["kickoff_beijing"])
        if generated>=tip:
            # Do not freeze a game for which forecast may have seen the result.
            if b.get("status")!="REJECTED_ASIAN_REPORT_NOT_PREMATCH":
                raise ValueError("UNREJECTED_POST_KICKOFF_FORECAST")
    return captured,generated

def market_direction(row,key):
    item=(row.get("markets") or {}).get(key) or {}
    if not isinstance(item.get("probabilities"),dict):return None
    if key=="ttg":
        goals=(item.get("goal_selection") or {}).get("goals")
        if not isinstance(goals,list) or not 1<=len(goals)<=2 or len(goals)!=len(set(goals)):
            return None
        return tuple(sorted(goals))
    return item.get("direction")

def hhad_line(snapshot_game):
    official=(snapshot_game.get("jc_markets") or {}).get("hhad")
    n=official.get("signed_home_handicap") if isinstance(official,dict) else None
    return n if type(n) is int else None

def asian_consensus(snapshot_game):
    market=snapshot_game.get("asian_007") or {}
    if snapshot_game.get("asian_007_status")!="VERIFIED_MATCH_ID_TIME_AND_COMPANY_SCHEMA":
        return None
    quotes=[]
    for book in market.get("companies") or []:
        try:
            quote=book["main"]["latest_quote"]
            ln=quote["signed_home_asian_handicap"]
            if type(ln) in (int,float) and math.isfinite(ln):
                quotes.append(float(ln))
        except (KeyError,TypeError):pass
    return statistics.median(quotes) if quotes else None

def source_facts(game):
    return {
      "match_id":str(game["match_id"]),
      "jc_number":game.get("jc_number"),
      "kickoff_beijing":game.get("kickoff_beijing"),
      "home_team":game.get("home_team"),"away_team":game.get("away_team"),
      "home_team_id_007":game.get("home_team_id_007"),
      "away_team_id_007":game.get("away_team_id_007"),
      "official_home_handicap":hhad_line(game),
      "asian_median_home_handicap":asian_consensus(game),
      "injury_report_state":game.get("injury_report_state"),
      "confirmed_absences":sorted(str(x.get("player_id")) for x in (game.get("injuries") or [])
                     if isinstance(x,dict) and x.get("status")=="VERIFIED"),
    }

def freeze(snapshot,forecast,scheduled_day,now=None):
    captured,generated=source_check(snapshot,forecast)
    now=(now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    day=datetime.strptime(scheduled_day,"%Y-%m-%d").date()
    slot=datetime(day.year,day.month,day.day,21,0,tzinfo=BJ).astimezone(timezone.utc)
    if now<slot or (now-slot).total_seconds()>MAX_DELAY*60:
        raise ValueError("OUTSIDE_BEIJING_2100_SCHEDULED_FINAL_WINDOW")
    # Scheduled GitHub Actions can begin late; use the actual timestamp,
    # allow up to 120 minutes after slot but never use a pre-slot report.
    if captured<slot or generated>now+timedelta(minutes=2):
        raise ValueError("NOT_LIVE_2100_SOURCE_WINDOW")
    if generated<slot or generated>=slot+timedelta(minutes=MAX_DELAY):
        raise ValueError("FORECAST_OUTSIDE_FINAL_SLOT_WINDOW")
    expected="周"+"一二三四五六日"[day.weekday()]
    if snapshot.get("jc_sale_day_beijing") and snapshot["jc_sale_day_beijing"]!=scheduled_day:
        raise ValueError("JC_SALE_DATE_DIFFERS_FROM_2100_BASELINE")
    if not snapshot["games"]:
        raise ValueError("NO_VERIFIED_JC_GAMES_TO_LOCK")
    if any(not str(g["jc_number"]).startswith(expected) for g in snapshot["games"]):
        raise ValueError("FROZEN_JC_OFFICIAL_WEEKDAY_DRIFT")
    games=[source_facts(g) for g in snapshot["games"]]
    return {"schema_version":VERSION,"slot_beijing_date":scheduled_day,
       "scheduled_slot_beijing":slot.astimezone(BJ).isoformat(),
       "actual_capture_utc":captured.isoformat(),
       "actual_model_generated_utc":generated.isoformat(),
       "frozen_at_utc":now.isoformat(),
       "model_version":forecast["model_version"],
       "source_snapshot_sha256":sha(snapshot),
       "final_forecast_sha256":sha(forecast),
       "scored_only_from_this_frozen_forecast":True,
       "no_shadow_model":True,
       "snapshot_facts":games,
       "forecast":forecast}

def safe_reason(old_fact,new_fact,old_row,new_row):
    reasons=[]
    a,b=old_fact.get("asian_median_home_handicap"),new_fact.get("asian_median_home_handicap")
    if isinstance(a,(int,float)) and isinstance(b,(int,float)) and abs(a-b)>=.25-1e-9:
        reasons.append(f"机构亚盘主队{a:+g}→{b:+g}")
    old_abs,new_abs=set(old_fact.get("confirmed_absences") or []),set(new_fact.get("confirmed_absences") or [])
    if old_abs!=new_abs and old_fact.get("injury_report_state")=="VERIFIED" and new_fact.get("injury_report_state")=="VERIFIED":
        reasons.append("已核实伤停名单有变")
    ha=(old_row.get("goal_expectation") or {}).get("home")
    hb=(new_row.get("goal_expectation") or {}).get("home")
    aa=(old_row.get("goal_expectation") or {}).get("away")
    ab=(new_row.get("goal_expectation") or {}).get("away")
    if all(type(x) in (float,int) for x in (ha,hb,aa,ab)):
        old_margin=ha-aa;new_margin=hb-ab
        if abs(new_margin-old_margin)>=.12:
            reasons.append(f"模型主客预期进球差{old_margin:+.2f}→{new_margin:+.2f}")
    if not reasons:reasons.append("模型概率更新；具体驱动因素尚未独立确认")
    return "；".join(reasons[:2])

def differences(locked,current_snapshot,current_forecast,now=None):
    if locked.get("schema_version")!=VERSION or not locked.get("scored_only_from_this_frozen_forecast"):
        raise ValueError("MISSING_VALID_2130_FROZEN_FORECAST")
    source_check(current_snapshot,current_forecast)
    now=(now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    day=datetime.strptime(locked["slot_beijing_date"],"%Y-%m-%d").date()
    expected=day+timedelta(days=1)
    local=now.astimezone(BJ)
    if local.date()!=expected or not (6<=local.hour<=9):
        raise ValueError("NOT_NEXT_BEIJING_0630_UPDATE_WINDOW")
    capture=as_dt(current_snapshot["captured_at_utc"])
    if capture<=as_dt(locked["actual_capture_utc"]) or capture>now+timedelta(minutes=2):
        raise ValueError("0630_MUST_BE_NEWER_THAN_FINAL")
    old_by={g["match_id"]:g for g in locked["forecast"]["games"]}
    fact_by={g["match_id"]:g for g in locked["snapshot_facts"]}
    new_facts={str(g["match_id"]):source_facts(g) for g in current_snapshot["games"]}
    rows=[]
    evaluated=0
    for now_row in current_forecast["games"]:
        mid=str(now_row["match_id"])
        if mid not in old_by:continue
        before=old_by[mid]
        old_fact=fact_by[mid];new_fact=new_facts[mid]
        if old_fact["jc_number"]!=new_fact["jc_number"] or any(old_fact[k]!=new_fact[k] for k in
                  ("home_team","away_team","home_team_id_007","away_team_id_007","kickoff_beijing")):
            raise ValueError("0630_007_FIXTURE_IDENTITY_DRIFT")
        if as_dt(new_fact["kickoff_beijing"])<=capture:
            continue # Match already underway cannot be "new prematch prediction."
        changed=[]
        evaluated+=1
        for key in KEYS:
            old_direction=market_direction(before,key)
            new_direction=market_direction(now_row,key)
            if old_direction is None or new_direction is None:
                continue
            old_h=old_fact.get("official_home_handicap")
            new_h=new_fact.get("official_home_handicap")
            if key=="hhad" and old_h!=new_h:
                # Different JC integer handicap => different betting event.
                changed.append({"market":key,"type":"OFFICIAL_JC_HANDICAP_LINE_CHANGED",
                    "old":old_direction,"new":new_direction,"old_home_handicap":old_h,
                    "new_home_handicap":new_h,"basis":"竞彩官方让球改线，不能按同一让球事件计算反转"})
                continue
            if old_direction!=new_direction:
                changed.append({"market":key,"type":"PREDICTION_REVERSED",
                    "old":old_direction,"new":new_direction,
                    "old_home_handicap":old_h if key=="hhad" else None,
                    "new_home_handicap":new_h if key=="hhad" else None,
                    "basis":safe_reason(old_fact,new_fact,before,now_row)})
        rows.append({"match_id":mid,"jc_number":old_fact["jc_number"],
            "home_team":old_fact["home_team"],"away_team":old_fact["away_team"],
            "kickoff_beijing":old_fact["kickoff_beijing"],
            "changes":changed})
    return {"schema_version":"football-jc-0630-vs-final-v1",
        "source_final_beijing_date":locked["slot_beijing_date"],
        "compared_to_only_2130_sha256":locked["final_forecast_sha256"],
        "current_forecast_sha256":sha(current_forecast),
        "actual_current_capture_utc":capture.isoformat(),
        "matched_prematch_games":evaluated,
        "reversals":sum(1 for r in rows for c in r["changes"] if c["type"]=="PREDICTION_REVERSED"),
        "changed_handicap_lines":sum(1 for r in rows for c in r["changes"] if c["type"]=="OFFICIAL_JC_HANDICAP_LINE_CHANGED"),
        "games":[r for r in rows if r["changes"]],
        "scoring_anchor_unchanged":True,
        "not_an_accuracy_grading_source":True}

def cli():
    p=argparse.ArgumentParser()
    p.add_argument("--mode",choices=("freeze","compare"),required=True)
    p.add_argument("--snapshot",required=True)
    p.add_argument("--forecast",required=True)
    p.add_argument("--day")
    p.add_argument("--locked")
    p.add_argument("--out",required=True)
    p.add_argument("--now")
    a=p.parse_args()
    def read(path):
        raw=Path(path).read_bytes()
        if len(raw)>22_000_000:raise ValueError("FOOTBALL_FILE_TOO_LARGE")
        return json.loads(raw)
    now=as_dt(a.now) if a.now else datetime.now(timezone.utc)
    snapshot=read(a.snapshot);forecast=read(a.forecast)
    if a.mode=="freeze":
        if not a.day:raise ValueError("SLOT_DAY_REQUIRED")
        result=freeze(snapshot,forecast,a.day,now)
    else:
        if not a.locked:raise ValueError("LOCKED_2130_FORECAST_REQUIRED")
        result=differences(read(a.locked),snapshot,forecast,now)
    path=Path(a.out)
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n","utf-8")
    if a.mode=="freeze":
        # The immutable 21:00 payload stores fixture facts under snapshot_facts,
        # not games. Reporting the legacy key silently printed zero for a
        # successfully frozen non-empty slate.
        source_games=len(snapshot["games"])
        frozen_games=len(result["snapshot_facts"])
        forecast_games=len(result["forecast"]["games"])
        if source_games!=frozen_games or frozen_games!=forecast_games:
            raise ValueError("FROZEN_2100_GAME_COUNT_MISMATCH")
        print("FOOTBALL_JC_FINAL_2100",a.mode,"source_games",frozen_games)
    else:
        print("FOOTBALL_JC_LEGACY_COMPARE",a.mode,"changed_games",len(result.get("games",[])))
if __name__=="__main__":cli()
