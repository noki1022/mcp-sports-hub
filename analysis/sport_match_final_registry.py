#!/usr/bin/env python3
"""Append-once point-in-time pregame answer registry shared by football and NBA.

Each candidate references an immutable captured snapshot and a forecast from the
same run. Only an already-created pre-kickoff answer can become the per-match
final after kickoff. Never rerun a model against a final score or a later quote.
"""
from __future__ import annotations
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from zoneinfo import ZoneInfo
import re

SCHEMA="sport-match-pregame-candidates-v1"
FINAL_SCHEMA="sport-match-pregame-final-v1"
SPORT_MARKETS={
    "football":("had","hhad","ttg"),
    "basketball":("JINGCAI_WIN","JINGCAI_HANDICAP","JINGCAI_TOTAL","CROWN_HANDICAP","CROWN_TOTAL"),
}

def stamp(v):
    try:
        d=datetime.fromisoformat(str(v).replace("Z","+00:00"))
    except (ValueError,TypeError) as e:
        raise ValueError("INVALID_AWARE_TIMESTAMP") from e
    if d.tzinfo is None:
        raise ValueError("TIMESTAMP_HAS_NO_TIMEZONE")
    return d.astimezone(timezone.utc)

def digest(obj):
    return hashlib.sha256(json.dumps(obj,sort_keys=True,ensure_ascii=False).encode()).hexdigest()

def require(test,reason):
    if not test:
        raise ValueError(reason)

def make_candidate(sport,snapshot,forecast,run_id,slot=""):
    require(sport in SPORT_MARKETS,"UNSUPPORTED_SPORT")
    require(str(run_id).isdigit(),"INVALID_RUN_ID")
    if sport=="football":
        require(snapshot.get("schema_version")=="football-jc-007-v1","WRONG_FOOTBALL_SOURCE")
        require(forecast.get("source_sha256")==digest(snapshot),"FOOTBALL_SOURCE_HASH_MISMATCH")
        require(forecast.get("model_version")=="football-jc-poisson-asian-assimilation-v2","ONLY_FUSED_FOOTBALL_MODEL_ALLOWED")
        captured=stamp(snapshot["captured_at_utc"])
        require(stamp(forecast["captured_at_utc"])==captured,"FOOTBALL_CAPTURE_DRIFT")
        generated=stamp(forecast["generated_at_utc"])
        originals={str(x["match_id"]):x for x in snapshot["games"]}
        predictions=forecast["games"]
    else:
        require(forecast.get("schema_version")=="nba-five-markets-v1","WRONG_NBA_FORECAST")
        require(snapshot.get("requested_display_date")==forecast.get("target_date"),"NBA_DATE_MISMATCH")
        captured=stamp(snapshot["captured_at_utc"])
        generated=stamp(forecast["analysis_generated_at_utc"])
        originals={str(x["game_id"]):x for x in snapshot["nba_cba_games"] if x.get("league")=="NBA"}
        predictions=forecast["games"]
    require(captured<=generated,"PREDICTION_BEFORE_SOURCE_CAPTURE")
    require(len(originals)==len(predictions) and bool(originals),"BOARD_IDENTITY_OR_COUNT_MISMATCH")
    seen=set()
    records=[]
    skipped=[]
    for row in predictions:
        mid=str(row.get("match_id" if sport=="football" else "game_id") or "")
        require(mid and mid not in seen and mid in originals,"DUPLICATE_OR_UNKNOWN_MATCH")
        seen.add(mid)
        orig=originals[mid]
        tip=stamp(orig["kickoff_beijing" if sport=="football" else "start_time_beijing"])
        row_tip=row.get("kickoff_beijing" if sport=="football" else "tipoff_beijing")
        require(row_tip is not None and stamp(row_tip)==tip,"PREDICTION_TIPOFF_DRIFT")
        for field in ("home_team","away_team"):
            require(bool(orig.get(field)) and orig.get(field)==row.get(field),"HOME_AWAY_IDENTITY_DRIFT")
        if sport=="football":
            require(orig.get("jc_number")==row.get("jc_number"),"FOOTBALL_JC_NUMBER_DRIFT")
            home_id=orig.get("home_team_id_007")
            away_id=orig.get("away_team_id_007")
            label=row.get("jc_number")
            extra_id=""
        else:
            require(str(orig.get("nba_game_id"))==str(row.get("nba_game_id")),"NBA_OFFICIAL_ID_DRIFT")
            home_id=orig.get("home_team_id") or orig.get("home_id") or orig.get("home_team")
            away_id=orig.get("away_team_id") or orig.get("away_id") or orig.get("away_team")
            label=row.get("jingcai_number")
            extra_id=str(row.get("nba_game_id"))
        if generated>=tip or captured>=tip:
            skipped.append({"match_id":mid,"reason":"NOT_PRETIP_CAPTURE_AND_GENERATION"})
            continue
        markets=row.get("markets") or {}
        require(set(markets)==set(SPORT_MARKETS[sport]),"MISSING_OR_EXTRA_MARKETS")
        checked=deepcopy(markets)
        for key,item in checked.items():
            require(isinstance(item,dict),"INVALID_MARKET_RECORD")
            if sport=="basketball" and item.get("status")=="DIRECTION_ISSUED":
                # Each quoted five-play signal must come from a pre-kickoff source.
                quote=stamp(item.get("captured_at_utc"))
                require(quote<=generated and quote<tip,"NON_PRETIP_BASKETBALL_MARKET")
        record={
            "sport":sport,"match_id":mid,"official_game_id":extra_id,
            "jc_number":label,"home_team":row["home_team"],"away_team":row["away_team"],
            "home_id":home_id,"away_id":away_id,
            "kickoff_utc":tip.isoformat(),"capture_utc":captured.isoformat(),
            "generated_utc":generated.isoformat(),"run_id":str(run_id),
            "planned_slot_beijing":str(slot),"model_version":forecast.get("model_version") or forecast.get("schema_version"),
            "source_snapshot_sha256":digest(snapshot),"forecast_sha256":digest(forecast),
            "markets":checked}
        record["record_sha256"]=digest(record)
        records.append(record)
    require(len(seen)==len(originals),"MISSING_FIXTURE_FORECAST")
    bundle={"schema_version":SCHEMA,"sport":sport,"run_id":str(run_id),
            "records":records,"skipped":skipped,"total_source_games":len(originals)}
    bundle["bundle_sha256"]=digest(bundle)
    return bundle

def check_bundle(b):
    require(b.get("schema_version")==SCHEMA and b.get("sport") in SPORT_MARKETS,"INVALID_BUNDLE_SCHEMA")
    h=b.get("bundle_sha256")
    require(h==digest({k:v for k,v in b.items() if k!="bundle_sha256"}),"BUNDLE_HASH_MISMATCH")
    for r in b.get("records",[]):
        require(r.get("sport")==b["sport"] and r.get("run_id")==b["run_id"],"BUNDLE_ROW_IDENTITY_DRIFT")
        require(r.get("record_sha256")==digest({k:v for k,v in r.items() if k!="record_sha256"}),
                "RECORD_HASH_MISMATCH")
        tip=stamp(r["kickoff_utc"])
        require(stamp(r["capture_utc"])<=stamp(r["generated_utc"])<tip,"POST_KICKOFF_OR_REVERSED_CANDIDATE")
        require(set(r["markets"])==set(SPORT_MARKETS[r["sport"]]),"MARKET_COVERAGE_DRIFT")

def select(bundles,as_of):
    now=stamp(as_of)
    grouped={}
    seen_records=set()
    identities={}
    for bundle in bundles:
        check_bundle(bundle)
        for r in bundle["records"]:
            k=(r["sport"],r["match_id"])
            identity=tuple(r.get(t) for t in ("official_game_id","jc_number","home_team","away_team",
                                             "home_id","away_id","kickoff_utc"))
            if k in identities and identities[k]!=identity:
                raise ValueError("FIXTURE_IDENTITY_OR_KICKOFF_CHANGED_REQUIRES_MANUAL_AUDIT:"+"/".join(k))
            identities[k]=identity
            if r["record_sha256"] in seen_records:
                continue  # retries of exactly the same evidence cannot count twice
            seen_records.add(r["record_sha256"])
            if stamp(r["generated_utc"])<=now:
                grouped.setdefault(k,[]).append(r)
    chosen=[]
    for key,rows in sorted(grouped.items()):
        rows.sort(key=lambda r:(stamp(r["generated_utc"]),stamp(r["capture_utc"]),int(r["run_id"])))
        latest=rows[-1]
        tip=stamp(latest["kickoff_utc"])
        reference=[r for r in rows if r["planned_slot_beijing"]=="2130"]
        baseline=reference[-1] if reference else None
        lead=(tip-stamp(latest["generated_utc"])).total_seconds()/60
        if lead<3:
            window="WITHIN_3_MINUTES_PRETIP"
        elif lead<=30:
            window="LAST_3_TO_30_MINUTES"
        else:
            window="EARLIER_VALID_PRETIP"
        chosen.append({
            "sport":key[0],"match_id":key[1],
            "official_game_id":latest["official_game_id"],
            "home_id":latest["home_id"],"away_id":latest["away_id"],
            "kickoff_utc":latest["kickoff_utc"],
            "state":"LOCKED_AFTER_KICKOFF" if now>=tip else "PENDING_MAY_STILL_CHANGE",
            "selection_rule":"LATEST_ACTUALLY_GENERATED_VERIFIED_PRETIP",
            "capture_utc":latest["capture_utc"],"generated_utc":latest["generated_utc"],
            "lead_minutes":round(lead,2),"window":window,
            "run_id":latest["run_id"],"model_version":latest["model_version"],
            "jc_number":latest["jc_number"],"home_team":latest["home_team"],"away_team":latest["away_team"],
            "source_snapshot_sha256":latest["source_snapshot_sha256"],
            "forecast_sha256":latest["forecast_sha256"],
            "original_candidate_sha256":latest["record_sha256"],
            "comparison_only_2130_sha256":baseline["record_sha256"] if baseline else None,
            "is_different_from_2130":bool(baseline and baseline["record_sha256"]!=latest["record_sha256"]),
            "markets":deepcopy(latest["markets"]),"valid_candidate_count":len(rows)})
    output={"schema_version":FINAL_SCHEMA,"as_of_utc":now.isoformat(),
            "scoring_contract":"SCORE_ONLY_LOCKED_AFTER_KICKOFF_USING_ORIGINAL_FORECAST",
            "selection_is_not_a_claim_of_greater_predictive_accuracy":True,
            "matched_games":chosen}
    output["registry_sha256"]=digest(output)
    return output

def publishable_final_documents(bundles,as_of,grace_minutes=90):
    """Only mature kickoff-time finals; stable bytes, no postgame data input."""
    require(type(grace_minutes) is int and 0<=grace_minutes<=1440,"INVALID_FINALIZATION_GRACE")
    now=stamp(as_of)
    idx=select(bundles,as_of)
    finished=[]
    for row in idx["matched_games"]:
        if row["state"]!="LOCKED_AFTER_KICKOFF":
            continue
        if (now-stamp(row["kickoff_utc"])).total_seconds()<grace_minutes*60:
            continue  # Give delayed GitHub Actions time to archive the last pretip run.
        require(re.fullmatch(r"[0-9]{1,20}",row["match_id"]) is not None,"UNSAFE_MATCH_ID")
        day=stamp(row["kickoff_utc"]).astimezone(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d")
        # No as_of time in per-match document: identical evidence = identical immutable file.
        final={k:deepcopy(row[k]) for k in ("sport","match_id","official_game_id",
             "home_id","away_id","kickoff_utc",
             "selection_rule","capture_utc","generated_utc","lead_minutes","window",
             "run_id","model_version","jc_number","home_team","away_team",
             "source_snapshot_sha256","forecast_sha256","original_candidate_sha256","markets")}
        final["schema_version"]="sport-per-match-locked-final-v1"
        final["kickoff_beijing_day"]=day
        final["scoring_eligible_only_with_independently_verified_final_score"]=True
        final["prematch_lock_only_no_result_source_read"]=True
        final["final_sha256"]=digest(final)
        finished.append(final)
    return finished

def publish_finals(bundles,as_of,out_dir,grace_minutes=90):
    outputs=[]
    for final in publishable_final_documents(bundles,as_of,grace_minutes):
        # One append-once file per sport, official match id, kickoff Beijing day.
        directory=Path(out_dir)/final["sport"]/final["kickoff_beijing_day"]
        path=directory/(final["sport"]+"-"+final["match_id"]+".final.json")
        state=save_once(path,final)
        outputs.append({"path":str(path),"state":state,"match_id":final["match_id"],
                        "sport":final["sport"],"forecast_sha256":final["forecast_sha256"]})
    return outputs

def save_once(path,document):
    dst=Path(path)
    dst.parent.mkdir(parents=True,exist_ok=True)
    data=json.dumps(document,ensure_ascii=False,indent=2,sort_keys=True)+"\n"
    if dst.exists():
        if dst.read_text(encoding="utf-8")!=data:
            raise ValueError("IMMUTABLE_FINAL_EXISTS_AND_DIFFERS")
        return "ALREADY_IDENTICAL"
    dst.write_text(data,encoding="utf-8")
    return "CREATED_APPEND_ONCE"

def main():
    p=argparse.ArgumentParser()
    sub=p.add_subparsers(dest="command",required=True)
    e=sub.add_parser("emit")
    e.add_argument("--sport",choices=tuple(SPORT_MARKETS),required=True)
    e.add_argument("--snapshot",required=True)
    e.add_argument("--forecast",required=True)
    e.add_argument("--run-id",required=True)
    e.add_argument("--slot",default="")
    e.add_argument("--out",required=True)
    s=sub.add_parser("select")
    s.add_argument("--bundle",action="append",default=[])
    s.add_argument("--bundle-dir")
    s.add_argument("--as-of",required=True)
    s.add_argument("--out",required=True)
    q=sub.add_parser("finalize")
    q.add_argument("--bundle",action="append",default=[])
    q.add_argument("--bundle-dir")
    q.add_argument("--as-of",required=True)
    q.add_argument("--grace-minutes",type=int,default=90)
    q.add_argument("--out-dir",required=True)
    a=p.parse_args()
    if a.command=="emit":
        doc=make_candidate(a.sport,json.loads(Path(a.snapshot).read_text(encoding="utf-8")),
                           json.loads(Path(a.forecast).read_text(encoding="utf-8")),a.run_id,a.slot)
        Path(a.out).parent.mkdir(parents=True,exist_ok=True)
        Path(a.out).write_text(json.dumps(doc,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        print("PRETIP_CANDIDATES_ARCHIVED",a.sport,len(doc["records"]),len(doc["skipped"]))
    else:
        paths=[Path(x) for x in a.bundle]
        if a.bundle_dir:
            paths+=sorted(Path(a.bundle_dir).rglob("*.json"))
        require(bool(paths),"MISSING_SNAPSHOT_CANDIDATES")
        docs=[json.loads(x.read_text(encoding="utf-8")) for x in paths]
        if a.command=="finalize":
            outputs=publish_finals(docs,a.as_of,a.out_dir,a.grace_minutes)
            print("MATCH_FINAL_APPEND_ONLY",len(outputs),sum(x["state"]=="CREATED_APPEND_ONCE" for x in outputs))
        else:
            result=select(docs,a.as_of)
            print("PER_MATCH_PRETIP_FINAL",save_once(a.out,result),len(result["matched_games"]))

if __name__=="__main__":main()
