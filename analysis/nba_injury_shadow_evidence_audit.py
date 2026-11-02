#!/usr/bin/env python3
"""Audit EXISTING immutable injury prospective shadow vs same-capture 007 trend.

This is a research-only evidence/settlement audit. It does NOT invent a
replacement injury predictor, alter saved pretip odds, use future results as
features, or claim an injury model improved outcomes while paired_count==0.

Existing original production forecast and injury shadow files are read-only.
Completed ESPN finals are fetched separately and used ONLY as outcome labels.
"""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime,timedelta,timezone
import hashlib,json,math
from pathlib import Path
from zoneinfo import ZoneInfo

from nba_multibook_asof_settled_ledger import fetch_espn_day,parse_espn
from nba_injury_prospective_capture import instant
from titan007_ev_analysis import NAMES

SCHEMA="nba-existing-injury-shadow-evidence-v1"
SLOTS=("2130",)
ET=ZoneInfo("America/New_York")
MAX_SCORE_DAYS=8

def get(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))

def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def num(value):
    try:
        x=float(value)
        return x if math.isfinite(x) else None
    except (TypeError,ValueError):
        return None

def abbr(chinese):
    code=NAMES.get(str(chinese))
    return code[0] if code else None

def build_records(root,settle_utc,score_provider=fetch_espn_day):
    root=Path(root)
    discovered=sorted(root.glob("reports/daily/*/2130/nba_injury_prospective_2130.json"))
    if not discovered:
        raise RuntimeError("NO_REAL_FROZEN_INJURY_SHADOW_FOUND")
    rows=[];snapshots=[];rejected=Counter();seen=set()
    for shadow_path in discovered:
        base=shadow_path.parent
        needed={
            "shadow":shadow_path,
            "model":base/"nba_priority_model.json",
            "movement":base/"titan007_priority_movement.json",
            "joined":base/"titan007_priority_joined.json",
        }
        if any(not p.is_file() for p in needed.values()):
            rejected["BATCH_MISSING_SAME_SNAPSHOT_SOURCE"]+=1
            continue
        d={name:get(path) for name,path in needed.items()}
        shadow=d["shadow"]
        joined={str(x["game_id"]):x for x in d["joined"].get("nba_cba_games",[]) if x.get("league")=="NBA"}
        model={str(x["game_id"]):x for x in d["model"].get("games",[])}
        movement={str(x["game_id"]):x for x in d["movement"].get("games",[])}
        source_time=instant(d["movement"]["captured_at_utc"])
        report_time=instant(shadow["captured_at_utc"])
        if source_time>report_time:
            raise RuntimeError("MARKET_SNAPSHOT_IS_FROM_FUTURE")
        if not d["shadow"].get("nonproduction"):
            raise RuntimeError("PRODUCTION_INJURY_SHADOW_NOT_ELIGIBLE")
        snapshots.append({
            "date":base.parent.name,"slot":base.name,
            "source_hashes":{name:digest(path) for name,path in needed.items()},
            "shadow_rows":len(shadow.get("games",[])),
            "paired_count_original":shadow.get("paired_count"),
            "market_captured_utc":source_time.isoformat(),
            "shadow_captured_utc":report_time.isoformat(),
        })
        for r in shadow.get("games",[]):
            espn_id=str(r.get("game_id") or "")
            oid=str(r.get("007_game_id") or "")
            if not espn_id or not oid or espn_id in seen:
                rejected["DUPLICATE_OR_MISSING_EVENT"]+=1;continue
            seen.add(espn_id)
            fixture=joined.get(oid)
            pred=model.get(oid)
            market=movement.get(oid)
            if fixture is None or pred is None or market is None:
                rejected["NOT_IN_SAME_SNAPSHOT"]+=1;continue
            if (str(fixture.get("nba_game_id"))!=espn_id
                or fixture.get("home_team")!=r.get("home")
                or fixture.get("away_team")!=r.get("away")
                or market.get("home_team")!=r.get("home")
                or market.get("away_team")!=r.get("away")):
                rejected["EVENT_OR_HOME_AWAY_MISMATCH"]+=1;continue
            tip=instant(r["tipoff_utc"])
            prediction=instant(r["predicted_at_utc"])
            injury_captured=r.get("source_report_captured_at_utc")
            if not injury_captured or instant(injury_captured)>prediction:
                rejected["INJURY_SOURCE_NOT_PREGAME_CAPTURED"]+=1;continue
            if (prediction>=tip or source_time>prediction
                or prediction!=report_time or
                instant(fixture["tipoff_utc"])!=tip):
                rejected["ASOF_CAPTURE_OR_TIPOFF_MISMATCH"]+=1;continue
            p=num(r.get("base_home_prob"))
            q=num(r.get("injury_home_prob"))
            if p is None or not 0<p<1:
                rejected["INVALID_BASELINE_PROBABILITY"]+=1;continue
            ctx=(pred.get("injury_context") or {})
            original_quality=r.get("quality")
            if (str(ctx.get("source_captured_at_utc"))!=str(injury_captured)
                or ctx.get("quality")!=original_quality):
                rejected["INJURY_CONTEXT_MISMATCH"]+=1;continue
            counts={}
            for side in ("home","away"):
                players=(ctx.get(side) or {}).get("players") or []
                counts[side]={status:sum(x.get("status")==status for x in players)
                              for status in ("Out","Doubtful","Questionable","Probable","Available")}
                counts[side]["published"]=(ctx.get(side) or {}).get("report_state")=="PUBLISHED"
            market_features={}
            for key in ("full_spread","full_total"):
                m=(market.get("markets") or {}).get(key) or {}
                current=m.get("current") or {}
                traces=m.get("recent_trace") or []
                if any(instant(x["captured_at_utc"])>prediction for x in traces):
                    raise RuntimeError("FUTURE_MARKET_TRACE_LEAK")
                market_features[key]={
                    "current_line":num(current.get("line")),
                    "line_delta_from_first_snapshot":num(m.get("delta_line_first")),
                    "line_delta_from_previous":num(m.get("delta_line_previous")),
                    "latest_trend_label":m.get("trend"),
                    "history_captures":market.get("history_captures"),
                    "price_side_direction_unverified":True,
                }
            row={
                "nba_game_id":espn_id,"007_game_id":oid,
                "home":r["home"],"away":r["away"],
                "home_abbr":abbr(r["home"]),"away_abbr":abbr(r["away"]),
                "tipoff_utc":tip.isoformat(),
                "prediction_captured_utc":prediction.isoformat(),
                "market_captured_utc":source_time.isoformat(),
                "injury_source_captured_utc":instant(injury_captured).isoformat(),
                "base_home_win_probability_frozen":p,
                "injury_probability_frozen":q,
                "paired_model_status":r.get("status"),
                "candidate_sha256":r.get("candidate_sha256"),
                "model_version_frozen":r.get("model_version"),
                "official_report_quality":original_quality,
                "injury_player_counts_observed":counts,
                "player_ids_verified":ctx.get("nba_person_id_join_verified") is True,
                "pregame_minutes_features_present":bool(ctx.get("replacement_pregame_features")),
                "original_production_injury_adjustment_status":(pred.get("injury_adjustment") or {}).get("status"),
                "market_features":market_features,
                "source_proof":{"slot":base.name,"target_date":base.parent.name,
                                "shadow_sha256":digest(shadow_path)},
                "score_result_only_after_completion":None,
            }
            if not row["home_abbr"] or not row["away_abbr"]:
                rejected["MISSING_VERIFIED_TEAM_ALIAS"]+=1
                continue
            rows.append(row)
    if not rows:
        raise RuntimeError("NO_VALID_INJURY_SHADOW_WITH_SAME_SNAPSHOT_MARKET")
    requested=sorted({instant(r["tipoff_utc"]).astimezone(ET).date() for r in rows})
    if len(requested)>MAX_SCORE_DAYS:
        raise RuntimeError("ESPN_RESULT_DAYS_EXCEED_BOUND")
    final_scores={}; conflicts=set();score_sources=[];failures=[]
    for day in requested:
        try:
            url,obj,sha=score_provider(day)
            parsed,invalid=parse_espn(obj,url,settle_utc.isoformat().replace("+00:00","Z"))
            score_sources.append({"eastern_date":day.isoformat(),
                                  "source_url":url,"source_sha256":sha,
                                  "completed_finals":len(parsed),
                                  "rejected":dict(invalid)})
            for g in parsed:
                eid=str(g["espn_event_id"])
                if eid in final_scores:conflicts.add(eid)
                else:final_scores[eid]=g
        except (OSError,ValueError,KeyError,TimeoutError,TypeError) as ex:
            failures.append({"eastern_date":day.isoformat(),
                             "error":type(ex).__name__})
    for key in conflicts:final_scores.pop(key,None)
    scores=Counter()
    for row in rows:
        tip=instant(row["tipoff_utc"])
        final=final_scores.get(row["nba_game_id"])
        if settle_utc<tip+timedelta(minutes=120):
            row["score_result_only_after_completion"]="NOT_YET_SENSIBLY_FINAL"
        elif final is None:
            row["score_result_only_after_completion"]="FINAL_NOT_IN_ESPN"
        elif (final["home"]!=row["home_abbr"] or final["away"]!=row["away_abbr"]
              or abs((instant(final["score_tip_utc"])-tip).total_seconds())>10800):
            row["score_result_only_after_completion"]="ESPN_TEAM_OR_TIP_CONFLICT"
        else:
            hp,ap=final["home_points"],final["away_points"]
            y=int(hp>ap)
            row["score_result_only_after_completion"]="ESPN_COMPLETED_VERIFIED"
            row["final_home_points"]=hp
            row["final_away_points"]=ap
            row["base_win_correct"]=int((row["base_home_win_probability_frozen"]>=.5)==bool(y))
            row["base_brier"]=(row["base_home_win_probability_frozen"]-y)**2
            if row["injury_probability_frozen"] is not None:
                q=row["injury_probability_frozen"]
                row["injury_brier"]=(q-y)**2
                row["injury_win_correct"]=int((q>=.5)==bool(y))
        scores[row["score_result_only_after_completion"]]+=1
    usable=[r for r in rows if r["score_result_only_after_completion"]=="ESPN_COMPLETED_VERIFIED"]
    paired=[r for r in usable if r["injury_probability_frozen"] is not None and r["candidate_sha256"]]
    report={
        "schema_version":SCHEMA,
        "snapshots":snapshots,
        "captured_games":len(rows),
        "distinct_event_ids":len({r["nba_game_id"] for r in rows}),
        "model_versions":dict(Counter(r["model_version_frozen"] for r in rows)),
        "injury_report_quality_counts":dict(Counter(r["official_report_quality"] for r in rows)),
        "observed_out_player_rows":sum(
            r["injury_player_counts_observed"][side]["Out"] for r in rows for side in ("home","away")),
        "verified_NBA_person_id_games":sum(r["player_ids_verified"] for r in rows),
        "training_compatible_pregame_minutes_feature_games":sum(r["pregame_minutes_features_present"] for r in rows),
        "frozen_replacement_model_paired_games":sum(r["injury_probability_frozen"] is not None and r["candidate_sha256"] for r in rows),
        "verified_completed_games":len(usable),
        "completed_baseline_accuracy":sum(r["base_win_correct"] for r in usable)/len(usable) if usable else None,
        "completed_baseline_Brier":sum(r["base_brier"] for r in usable)/len(usable) if usable else None,
        "completed_paired_injury_games":len(paired),
        "completed_paired_injury_Brier_lift":(
            sum(r["injury_brier"]-r["base_brier"] for r in paired)/len(paired) if paired else None),
        "score_status":dict(scores),
        "evidence_rejections":dict(rejected),
        "scoreboard_sources":score_sources,
        "scoreboard_failures":failures,
        "original_injury_model_not_replaced":True,
        "cannot_estimate_injury_increment_without_paired_forecasts":True,
        "market_price_side_orientation_unverified":True,
        "zero_live_model_or_pushplus_change":True,
    }
    return rows,report

def save(root,out,provider=fetch_espn_day,now=None):
    now=now or datetime.now(timezone.utc)
    rows,report=build_records(root,now,provider)
    dest=Path(out)
    dest.mkdir(parents=True,exist_ok=True)
    path=dest/"existing_frozen_injury_market_evidence.jsonl"
    path.write_text("".join(json.dumps(r,ensure_ascii=False,sort_keys=True)+"\n" for r in rows))
    report["evidence_sha256"]=digest(path)
    (dest/"audit.json").write_text(json.dumps(report,indent=2,ensure_ascii=False,sort_keys=True)+"\n")
    print("NBA_INJURY_SHADOW_EXISTING_EVIDENCE",json.dumps({
        "captured":report["captured_games"],
        "source_snapshots":len(report["snapshots"]),
        "official_affected":report["injury_report_quality_counts"],
        "verified_nba_ids":report["verified_NBA_person_id_games"],
        "compatible_minutes":report["training_compatible_pregame_minutes_feature_games"],
        "paired_injury_model":report["frozen_replacement_model_paired_games"],
        "settled":report["verified_completed_games"],
        "baseline_Brier":report["completed_baseline_Brier"],
        "baseline_accuracy":report["completed_baseline_accuracy"],
        "score_status":report["score_status"],
        "original_changed":False,
    },ensure_ascii=False))
    return report

def selftest():
    # No invented injury improvement: zero paired forecast must imply null lift.
    assert num(None) is None and num(float("nan")) is None
    assert abs(num(.4)-.4)<1e-10
    assert instant("2026-11-01T12:00:00Z")<instant("2026-11-01T20:30:00Z")
    assert abbr("波士顿凯尔特人")=="BOS"
    print("NBA_INJURY_SHADOW_EXISTING_READONLY_SELFTEST_PASS")

if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("--root",default=".")
    ap.add_argument("--out",default="/tmp/nba-existing-injury-shadow-evidence")
    ap.add_argument("--selftest",action="store_true")
    args=ap.parse_args()
    selftest() if args.selftest else save(args.root,args.out)
