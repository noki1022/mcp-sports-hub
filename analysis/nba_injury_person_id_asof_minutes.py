#!/usr/bin/env python3
"""Research-only evidence builder for EXISTING archived NBA injury shadow records.

Maps pretip official report names to stable player IDs in historical game logs
and calculates strictly *prior* minutes. No player effect coefficients,
proposed injury probability, original archive mutation, or live integration.
Refuse ambiguous names/team memberships; missing playing logs are UNKNOWN,
not proof of zero injury impact or confirmed DNP.
"""
from __future__ import annotations

import argparse
from collections import Counter,defaultdict
from datetime import datetime,timezone
from hashlib import sha256
from io import BytesIO
import json
import math
from pathlib import Path
import re
import unicodedata
from urllib.request import urlopen,Request
from zoneinfo import ZoneInfo

import pandas as pd
from nba_injury_prospective_capture import instant
from titan007_ev_analysis import NAMES

BASE="https://huggingface.co/datasets/cbratkovics/nba-game-logs/resolve/main/game_logs/"
SEASONS=("2025-26","2026-27")
MAX_SOURCE_BYTES=3_000_000
MAX_LOG_DAYS_PRIOR=410
CURRENT_SEASON="2026-27"
ET=ZoneInfo("America/New_York")
SCHEMA="nba-existing-injury-person-id-prior-minutes-v1"
MIN_TEAM_HISTORY=3

def name(x):
    x=str(x or "")
    if "," in x:
        before,after=x.split(",",1)
        x=after+" "+before
    x=unicodedata.normalize("NFKD",x).casefold()
    x="".join(ch for ch in x if not unicodedata.combining(ch))
    x=re.sub(r"\b(jr|sr|ii|iii|iv|v)\b"," ",x)
    return " ".join(re.sub(r"[^a-z ]"," ",x).split())

def team(x):
    aliases={"GS":"GSW","SA":"SAS","NY":"NYK","NO":"NOP",
             "UTAH":"UTA","WSH":"WAS","BRK":"BKN","CHO":"CHA",
             "PHO":"PHX"}
    raw=str(x or "").upper()
    return aliases.get(raw,raw)

def abbr(chinese):
    row=NAMES.get(str(chinese))
    return team(row[0]) if row else None

def get_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))

def sha(path):
    return sha256(Path(path).read_bytes()).hexdigest()

def download_logs(season,fetcher=None):
    url=BASE+"game_logs_"+season+".parquet"
    if fetcher is None:
        def fetcher(u):
            request=Request(u,headers={"User-Agent":"NBA-injury-shadow-research-evidence/1.0"})
            with urlopen(request,timeout=35) as r:
                return r.read(MAX_SOURCE_BYTES+1)
    data=fetcher(url)
    if not 1000<len(data)<=MAX_SOURCE_BYTES:
        raise RuntimeError("PLAYER_SOURCE_SIZE_OUT_OF_BOUNDS")
    df=pd.read_parquet(BytesIO(data))
    expected={"game_id","game_date","player_id","player_name","team","minutes"}
    if not expected.issubset(set(df.columns)):
        raise RuntimeError("MISSING_STABLE_PLAYER_GAME_SCHEMA")
    return df,{"season":season,"url":url,"sha256":sha256(data).hexdigest(),
               "source_rows":len(df),"source_published_utc_independently_verified":False,
               "license_and_upstream_rights_need_independent_review":True}

def validated_history(frames):
    seen=set();invalid=Counter();rows=[]
    identity=defaultdict(set)
    for season,frame in frames:
        for row in frame.itertuples(index=False):
            try:
                d=pd.Timestamp(row.game_date).date().isoformat()
                pid=str(int(row.player_id))
                g=str(row.game_id).strip()
                normalized=name(row.player_name)
                club=team(row.team)
                minutes=float(row.minutes)
                if (not re.fullmatch(r"20\d\d-\d\d-\d\d",d)
                    or not pid.isdecimal() or not g
                    or not normalized or club not in {
                        "ATL","BOS","BKN","CHA","CHI","CLE","DAL","DEN","DET",
                        "GSW","HOU","IND","LAC","LAL","MEM","MIA","MIL","MIN",
                        "NOP","NYK","OKC","ORL","PHI","PHX","POR","SAC","SAS",
                        "TOR","UTA","WAS"} or not math.isfinite(minutes)
                    or not 0<minutes<=65):
                    invalid["INVALID_LOG_ROW"]+=1;continue
                key=(g,pid)
                if key in seen:
                    invalid["DUPLICATE_PLAYER_GAME"]+=1
                    continue
                seen.add(key)
                identity[pid].add(normalized)
                rows.append({"date":d,"person_id":pid,"name":normalized,
                             "team":club,"minutes":minutes,
                             "season":season,"game_id":g})
            except (TypeError,ValueError,AttributeError,OverflowError):
                invalid["UNPARSEABLE_PLAYER_ROW"]+=1
    ambiguous={pid for pid,names in identity.items() if len(names)>1}
    # Different source player_name strings for the same stable ID may reflect
    # renames or nicknames. Quarantine instead of silently collapsing.
    if ambiguous:
        invalid["PLAYER_ID_HAS_MULTIPLE_NAMES"]=len(ambiguous)
    rows=[r for r in rows if r["person_id"] not in ambiguous]
    rows.sort(key=lambda r:(r["date"],r["game_id"],r["person_id"]))
    return rows,dict(sorted(invalid.items()))

def archive_fixtures(root):
    paths=sorted(Path(root).glob("reports/daily/*/2130/nba_injury_prospective_2130.json"))
    if not paths:raise RuntimeError("NO_EXISTING_INJURY_SHADOW_ARCHIVES")
    games=[];snapshots=[]
    for path in paths:
        model_path=path.parent/"nba_priority_model.json"
        joined_path=path.parent/"titan007_priority_joined.json"
        if not model_path.is_file() or not joined_path.is_file():
            raise RuntimeError("SAME_SLOT_MODEL_OR_FIXTURE_MISSING")
        snapshot=get_json(path)
        model=get_json(model_path)
        joined=get_json(joined_path)
        mapping={str(x["game_id"]):x for x in model.get("games",[])}
        fixture={str(x["game_id"]):x for x in joined.get("nba_cba_games",[])}
        snapshots.append({
            "date":path.parent.parent.name,
            "slot":path.parent.name,
            "original_injury_shadow_sha256":sha(path),
            "original_model_sha256":sha(model_path),
            "original_fixture_sha256":sha(joined_path),
            "original_paired_count":snapshot.get("paired_count"),
        })
        for r in snapshot.get("games",[]):
            oid=str(r.get("007_game_id") or "")
            eid=str(r.get("game_id") or "")
            m=mapping.get(oid)
            f=fixture.get(oid)
            if not m or not f or str(f.get("nba_game_id"))!=eid:
                raise RuntimeError("SAME_SNAPSHOT_EVENT_ID_MISMATCH")
            if f.get("home_team")!=r.get("home") or f.get("away_team")!=r.get("away"):
                raise RuntimeError("SOURCE_HOME_AWAY_CONFLICT")
            prediction=instant(r["predicted_at_utc"])
            tip=instant(r["tipoff_utc"])
            source=instant(r["source_report_captured_at_utc"])
            if not source<=prediction<tip:
                raise RuntimeError("OFFICIAL_SHADOW_TIME_CONFLICT")
            context=m.get("injury_context") or {}
            if context.get("quality")!=r.get("quality"):
                raise RuntimeError("SOURCE_QUALITY_MISMATCH")
            if instant(context["source_captured_at_utc"])!=source:
                raise RuntimeError("SOURCE_CAPTURE_TIMESTAMP_CONFLICT")
            if m.get("model_probability",{}).get("home")!=r.get("base_home_prob"):
                raise RuntimeError("FROZEN_MODEL_PROBABILITY_MISMATCH")
            games.append({"event_id":eid,"007_game_id":oid,"home":r["home"],
                          "away":r["away"],"home_code":abbr(r["home"]),
                          "away_code":abbr(r["away"]),
                          "prediction_utc":prediction,"tipoff_utc":tip,
                          "source_utc":source,"quality":context.get("quality"),
                          "injury_context":context,
                          "original_candidate_status":r.get("status"),
                          "original_injury_prob":r.get("injury_home_prob"),
                          "source_snapshot_sha256":sha(path)})
    if len({r["event_id"] for r in games})!=len(games):
        raise RuntimeError("DUPLICATE_FROZEN_EVENT_ID")
    return games,snapshots

def candidate_index(history,asof_date):
    # No same Eastern date games: all features were available before the
    # original fixture date; other games on that day never become features.
    eligible=[r for r in history if r["date"]<asof_date]
    by_name=defaultdict(set)
    by_person=defaultdict(list)
    for r in eligible:
        by_name[r["name"]].add(r["person_id"])
        by_person[r["person_id"]].append(r)
    return by_name,by_person

def match(name_raw,club,history,asof_date):
    n=name(name_raw)
    by_name,by_person=candidate_index(history,asof_date)
    ids=by_name.get(n,set())
    if len(ids)==0:
        return {"status":"NAME_NOT_PRESENT_IN_PAST_PLAYER_LOGS",
                "player_id":None,"prior_minutes":None}
    if len(ids)>1:
        return {"status":"AMBIGUOUS_PLAYER_NAME_MULTI_ID",
                "player_id":None,"prior_minutes":None}
    pid=next(iter(ids))
    entries=by_person[pid]
    if any(r["date"]>=asof_date for r in entries):
        raise RuntimeError("FUTURE_PLAYER_LOG_LEAK")
    own=[r for r in entries if r["team"]==club]
    # Transfers must not borrow minutes from the old team as evidence of
    # membership in the reported club. Do not infer roster or DNP from missing.
    if not own:
        return {"status":"NO_VERIFIED_LOG_WITH_REPORT_TEAM",
                "player_id":pid,"prior_minutes":None}
    if entries[-1]["team"]!=club:
        return {"status":"LATEST_PLAYER_TEAM_DISAGREES",
                "player_id":pid,"prior_minutes":None}
    if len(own)<MIN_TEAM_HISTORY:
        return {"status":"INSUFFICIENT_PRIOR_MINUTE_GAMES",
                "player_id":pid,"prior_minutes":None}
    recent=own[-8:]
    sample=entries[-1]
    if sample["date"]<"2026-07-01":
        membership="PREVIOUS_SEASON_ONLY_MEMBERSHIP_UNCONFIRMED"
    else:
        membership="CURRENT_SEASON_PLAYED_ON_REPORT_TEAM"
    return {
        "status":"ASOF_PLAYER_ID_AND_PRIOR_MINUTES_RESEARCH_ONLY",
        "player_id":pid,
        "source_player_normalized_name":n,
        "team_at_last_prior_game":sample["team"],
        "last_prior_game_date":sample["date"],
        "same_team_prior_games":len(own),
        "recent_prior_games_used":len(recent),
        "prior_minutes":round(sum(r["minutes"] for r in recent)/len(recent),5),
        "current_team_membership_evidence":membership,
        "ready_for_live_replacement_model":False,
    }

def audit(history,games,snapshots,source):
    result=[];counts=Counter()
    for g in games:
        report_date=g["tipoff_utc"].astimezone(ET).date().isoformat()
        if not g["home_code"] or not g["away_code"]:
            raise RuntimeError("UNKNOWN_TEAM_CODE")
        players=[]
        for side in ("home","away"):
            club=g[side+"_code"]
            for record in ((g["injury_context"].get(side) or {}).get("players") or []):
                status=record.get("status")
                if status not in ("Out","Doubtful","Questionable","Probable","Available"):
                    counts["UNKNOWN_DESIGNATION"]+=1;continue
                matched=match(record.get("name"),club,history,report_date)
                counts[matched["status"]]+=1
                players.append({"name_in_official_report":record.get("name"),
                                "report_designation":status,
                                "report_team":club,
                                "home_or_away":side,
                                **matched})
        matched=[p for p in players if p["status"]=="ASOF_PLAYER_ID_AND_PRIOR_MINUTES_RESEARCH_ONLY"]
        membership=[p for p in matched if p["current_team_membership_evidence"]=="CURRENT_SEASON_PLAYED_ON_REPORT_TEAM"]
        result.append({
            "nba_game_id":g["event_id"],
            "007_game_id":g["007_game_id"],
            "official_report_quality":g["quality"],
            "pregame_prediction_utc":g["prediction_utc"].isoformat(),
            "official_report_captured_utc":g["source_utc"].isoformat(),
            "tipoff_utc":g["tipoff_utc"].isoformat(),
            "frozen_original_injury_probability":g["original_injury_prob"],
            "frozen_original_candidate_status":g["original_candidate_status"],
            "official_player_report_rows":len(players),
            "research_unique_id_with_past_minutes":len(matched),
            "research_current_season_team_verified_players":len(membership),
            "reported_players":players,
            "original_archive_sha256":g["source_snapshot_sha256"],
            "candidate_feature_schema":"nba-id-current-team-prior-minutes-v1",
            "candidate_feature_vector":None,
            "current_production_injury_probability_modified":False,
            "no_player_impact_coefficient_fabricated":True,
        })
    summary={
        "schema_version":SCHEMA,
        "existing_frozen_games":len(games),
        "original_archive_batches":snapshots,
        "historical_log_sources":source,
        "historical_log_unique_games":len({r["game_id"] for r in history}),
        "historical_log_unique_person_ids":len({r["person_id"] for r in history}),
        "official_player_rows":sum(r["official_player_report_rows"] for r in result),
        "player_id_with_prior_minutes":sum(r["research_unique_id_with_past_minutes"] for r in result),
        "current_season_team_verified_reported_players":sum(r["research_current_season_team_verified_players"] for r in result),
        "identity_resolution_status_counts":dict(sorted(counts.items())),
        "original_injury_paired_probability_games":sum(r["frozen_original_injury_probability"] is not None for r in result),
        "no_historical_quote_update_time_inferred":True,
        "future_result_or_minutes_as_features":False,
        "name_only_current_roster_membership_assumed":False,
        "original_frozen_predictions_unmodified":True,
        "no_new_injury_model_coefficients_generated":True,
        "no_live_scheduler_or_pushplus_changes":True,
    }
    return result,summary

def run(root,out):
    loaded=[];sources=[]
    for season in SEASONS:
        frame,src=download_logs(season)
        loaded.append((season,frame))
        sources.append(src)
    history,invalid=validated_history(loaded)
    games,snapshots=archive_fixtures(root)
    result,report=audit(history,games,snapshots,sources)
    report["source_validation_rejections"]=invalid
    dest=Path(out);dest.mkdir(parents=True,exist_ok=True)
    evidence=dest/"injury_existing_shadow_player_asof_evidence.jsonl"
    evidence.write_text("".join(json.dumps(x,sort_keys=True,ensure_ascii=False)+"\n" for x in result),encoding="utf-8")
    report["evidence_file_sha256"]=sha(evidence)
    (dest/"audit.json").write_text(json.dumps(report,sort_keys=True,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("NBA_EXISTING_INJURY_ID_MINUTES_EVIDENCE",json.dumps({
        "frozen_games":report["existing_frozen_games"],
        "player_report_rows":report["official_player_rows"],
        "identified_prior_minutes":report["player_id_with_prior_minutes"],
        "current_season_team_verified":report["current_season_team_verified_reported_players"],
        "identity_status":report["identity_resolution_status_counts"],
        "log_player_count":report["historical_log_unique_person_ids"],
        "new_probabilities":0,
        "production_changed":False,
    },ensure_ascii=False))
    return report

def selftest():
    assert name("Banchero, Paolo")=="paolo banchero"
    assert name("Carter Jr., Wendell")=="wendell carter"
    h=[
        {"date":"2026-10-20","team":"ORL","person_id":"123","name":"paolo banchero","minutes":32,"game_id":"1"},
        {"date":"2026-10-21","team":"ORL","person_id":"123","name":"paolo banchero","minutes":34,"game_id":"2"},
        {"date":"2026-10-22","team":"ORL","person_id":"123","name":"paolo banchero","minutes":36,"game_id":"3"},
        {"date":"2026-11-20","team":"ORL","person_id":"123","name":"paolo banchero","minutes":40,"game_id":"4"}]
    x=match("Banchero, Paolo","ORL",h,"2026-11-01")
    assert x["player_id"]=="123" and x["prior_minutes"]==34
    assert x["last_prior_game_date"]=="2026-10-22"
    assert x["current_team_membership_evidence"]=="CURRENT_SEASON_PLAYED_ON_REPORT_TEAM"
    assert match("Banchero, Paolo","NYK",h,"2026-11-01")["prior_minutes"] is None
    extra=[{"date":"2026-10-20","team":"ORL","person_id":"456","name":"paolo banchero","minutes":20,"game_id":"5"}]
    assert match("Banchero, Paolo","ORL",h+extra,"2026-11-01")["status"]=="AMBIGUOUS_PLAYER_NAME_MULTI_ID"
    # Same-day or later minutes forbidden even when already in source file.
    x=match("Banchero, Paolo","ORL",h,"2026-10-22")
    assert x["status"]=="INSUFFICIENT_PRIOR_MINUTE_GAMES"
    print("NBA_INJURY_STABLE_ID_ASOF_MINUTES_SELFTEST_PASS")

if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("--root",default=".")
    ap.add_argument("--out",default="/tmp/nba-injury-stable-identity-asof-minutes")
    ap.add_argument("--selftest",action="store_true")
    args=ap.parse_args()
    selftest() if args.selftest else run(args.root,args.out)
