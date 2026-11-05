#!/usr/bin/env python3
"""Single scorecard for independently sealed, latest-pretip football and NBA finals.

No odds collection and no model recomputation. Football grading additionally
requires the original bytes of the independently audited 007 FULL-TIME feed.
NBA scoring must be supplied from the established independent official scorer.
"""
from __future__ import annotations
import argparse,json,hashlib,sys
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path
from zoneinfo import ZoneInfo
sys.path.insert(0,str(Path(__file__).resolve().parent))
import sport_match_final_registry as registry
import football_jc_prospective_score as ft
from nba_five_market_settlement import settle as nba_settle, MARKETS as NBA_MARKETS

LABELS={"football":("had","hhad","ttg"),"basketball":tuple(NBA_MARKETS)}
def validate_final(f):
    registry.require(f.get("schema_version")=="sport-per-match-locked-final-v1","NOT_PER_MATCH_PRETIP_FINAL")
    registry.require(f.get("final_sha256")==registry.digest({k:v for k,v in f.items() if k!="final_sha256"}),
                     "PER_MATCH_FINAL_HASH_MISMATCH")
    registry.require(f.get("prematch_lock_only_no_result_source_read") is True,"PREGAME_SOURCE_MISSING")
    registry.require(f.get("sport") in LABELS and set(f.get("markets",{}))==set(LABELS[f["sport"]]),
                     "FINAL_MARKET_IDENTITY_MISMATCH")
    registry.require(registry.stamp(f["generated_utc"])<registry.stamp(f["kickoff_utc"]),"NOT_PREKICKOFF")
    registry.require(registry.stamp(f["capture_utc"])<=registry.stamp(f["generated_utc"]),"CAPTURE_GENERATION_REVERSED")
    registry.require(bool(f.get("source_snapshot_sha256")) and bool(f.get("original_candidate_sha256")),
                     "MISSING_HASHED_ORIGINAL")
    registry.require(f.get("kickoff_beijing_day")==registry.stamp(f["kickoff_utc"]).astimezone(
                     ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d"),"KICKOFF_DAY_MISMATCH")
    return True

def load_finals(root,sport,day):
    registry.require(sport in LABELS,"BAD_SPORT")
    registry.require(len(day)==8 and day.isdigit(),"INVALID_DAY")
    base=Path(root)/sport/day
    files=sorted(base.glob("*.final.json")) if base.exists() else []
    rows=[];seen=set()
    for file in files:
        data=json.loads(file.read_text(encoding="utf-8"))
        validate_final(data)
        registry.require(data["sport"]==sport and data["kickoff_beijing_day"]==day,"FINAL_FILE_DAY_OR_SPORT_DRIFT")
        mid=data["match_id"]
        registry.require(mid not in seen,"DUPLICATE_FINAL_FOR_ONE_MATCH")
        seen.add(mid);rows.append(data)
    return rows

def football_grade(finals,results,raw_evidence):
    # A 007 status label with no original bytes is NOT an independently verified FT.
    verified=ft.validate_results(results,raw_evidence)
    graded=[];total={k:Counter() for k in LABELS["football"]}
    for f in finals:
        validate_final(f)
        mid=f["match_id"];res=verified.get(mid)
        line=(f["markets"]["hhad"] or {}).get("signed_home_handicap")
        info={"match_id":mid,"jc_number":f["jc_number"],"home_team":f["home_team"],
              "away_team":f["away_team"],"kickoff_utc":f["kickoff_utc"],
              "pregame_candidate_sha256":f["original_candidate_sha256"],
              "actual_score":None,"markets":{}}
        if res is not None:
            ft.verify_join({"match_id":mid,"jc_number":f["jc_number"],"kickoff_beijing":f["kickoff_utc"],
                            "home_team_id_007":f["home_id"],"away_team_id_007":f["away_id"]},
                           res,registry.stamp(f["generated_utc"]))
            h,a=res["home_goals"],res["away_goals"]
            info["actual_score"]={"home":h,"away":a}
        for key in LABELS["football"]:
            m=f["markets"][key]
            prices=m.get("jc_odds")
            predicted=(m.get("goal_selection") or {}).get("goals") if key=="ttg" else [m.get("direction")]
            if not isinstance(predicted,list):predicted=[]
            predicted=[v for v in predicted if isinstance(v,str) and v]
            actual=None
            if res is not None:
                if key=="had":actual="主胜" if h>a else "平" if h==a else "客胜"
                elif key=="hhad" and type(line) is int:
                    n=h+line-a
                    actual="让胜" if n>0 else "让平" if n==0 else "让负"
                elif key=="ttg":
                    actual=str(h+a)+"球" if h+a<7 else "7+球"
            if res is None:status="UNSETTLED"
            elif prices is None:status="EXCLUDED_NOT_ON_SALE"
            elif actual is None or not predicted:status="EXCLUDED_NO_VALID_DIRECTION"
            else:status="HIT" if actual in predicted else "MISS"
            total[key][status]+=1
            info["markets"][key]={"direction":predicted,"actual":actual,"status":status,
                                    "official_home_handicap":line if key=="hhad" else None}
        graded.append(info)
    return graded,total

def verify_nba_final_score_identity(final,source):
    """Do not turn a completed score for a wrong home/away or postponed event into a hit."""
    if source.get("completed") is not True:
        return
    if type(source.get("home_points")) is not int or type(source.get("away_points")) is not int:
        raise ValueError("NBA_COMPLETED_WITHOUT_VALID_INTEGER_SCORE")
    if source["home_points"]==source["away_points"] or min(source["home_points"],source["away_points"])<0:
        raise ValueError("NBA_INVALID_FINAL_SCORE")
    tip=source.get("tip_beijing")
    registry.require(tip is not None and abs((registry.stamp(tip)-registry.stamp(final["kickoff_utc"])).total_seconds())<=300,
                     "NBA_FINAL_EVENT_TIPOFF_NOT_SAME_PRETIP_MATCH")
    # 007 Chinese teams were already crossed to the ESPN official fixture at source capture.
    # Re-verify the FULL-TIME feed's sides with that same controlled name mapping.
    from titan007_ev_analysis import NAMES
    home=NAMES.get(final["home_team"])
    away=NAMES.get(final["away_team"])
    registry.require(home is not None and away is not None and home[0]!=away[0],
                     "NBA_UNVERIFIED_FROZEN_TEAM_IDENTITY")
    registry.require(str(source.get("home_abbr") or "").upper()==home[0] and
                     str(source.get("away_abbr") or "").upper()==away[0],
                     "NBA_OFFICIAL_RESULT_HOME_AWAY_SWAPPED_OR_UNKNOWN")

def basketball_grade(finals,scores,day):
    for f in finals:
        validate_final(f)
        if f.get("official_game_id") in scores:
            verify_nba_final_score_identity(f,scores[f["official_game_id"]])
    board={"target_date":datetime.strptime(day,"%Y%m%d").strftime("%Y-%m-%d"),
           "games":[{"game_id":f["match_id"],"nba_game_id":f["official_game_id"],
                     "jingcai_number":f["jc_number"],"home_team":f["home_team"],
                     "away_team":f["away_team"],"tipoff_beijing":f["kickoff_utc"],
                     "markets":f["markets"]} for f in finals]}
    settled=nba_settle(board,scores,board["target_date"])
    per=settled["games"]
    byid={f["match_id"]:f for f in finals}
    totals={k:Counter() for k in LABELS["basketball"]}
    for item in per:
        f=byid[item["game_id"]]
        item["pregame_candidate_sha256"]=f["original_candidate_sha256"]
        for k,v in item["markets"].items():
            totals[k][v["outcome"]]+=1
    return per,totals

def result(sport,day,rows,counters):
    details={}
    for k,c in counters.items():
        good=c["HIT"];bad=c["MISS"];den=good+bad
        details[k]={"hits":good,"misses":bad,"graded":den,
                    "hit_rate":round(good/den,6) if den else None,
                    "pushes":c["PUSH"],
                    "unsettled":c["UNSETTLED"],
                    "excluded":sum(v for x,v in c.items() if x.startswith("EXCLUDED"))}
    report={"schema_version":"sports-latest-pretip-scoring-v1","sport":sport,"beijing_day":day,
            "prediction_source":"LATEST_VERIFIED_PREKICKOFF_PER_MATCH_IMMUTABLE",
            "historical_2130_not_graded_separately":True,
            "official_result_validation_required":True,
            "matches":rows,"summary":details}
    report["review_sha256"]=registry.digest(report)
    return report

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--final-root",required=True);p.add_argument("--sport",required=True,choices=tuple(LABELS))
    p.add_argument("--day",required=True);p.add_argument("--results",required=True)
    p.add_argument("--raw-dir");p.add_argument("--out",required=True)
    a=p.parse_args()
    finals=load_finals(a.final_root,a.sport,a.day)
    if not finals:raise ValueError("NO_SEALED_PER_MATCH_FINALS_NO_SCORECARD")
    results=json.loads(Path(a.results).read_text(encoding="utf-8"))
    if a.sport=="basketball":
        if not isinstance(results,dict):raise ValueError("INVALID_NBA_OFFICIAL_RESULTS_MAP")
        rows,totals=basketball_grade(finals,results,a.day)
    else:
        if not a.raw_dir:raise ValueError("ORIGINAL_007_RAW_FT_BYTES_MANDATORY")
        raw={p.stem: p.read_bytes() for p in Path(a.raw_dir).glob("*.bin")}
        rows,totals=football_grade(finals,results,raw)
    report=result(a.sport,a.day,rows,totals)
    Path(a.out).parent.mkdir(parents=True,exist_ok=True)
    Path(a.out).write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("VERIFIED_PER_MATCH_REVIEW",a.sport,[(k,x["graded"]) for k,x in report["summary"].items()])

if __name__=="__main__":main()
