#!/usr/bin/env python3
"""Explain 007 football direction/odds/Asian/injury changes between real captures.

Read-only. Never train with future snapshots, invent absent probabilities, nor
assume last snapshot has better accuracy. An initial/no-history capture is valid.
"""
from __future__ import annotations
import argparse,json,math
from pathlib import Path
import sport_match_final_registry as R
VERSION="football-007-asof-hourly-movement-v1"
MARKETS=R.SPORT_MARKETS["football"]

def direction(m,key):
    if key=="ttg":
        x=(m.get("goal_selection") or {}).get("goals")
        return tuple(x) if isinstance(x,list) else None
    return m.get("direction")
def n(v):
    if type(v) not in (int,float):return None
    if not math.isfinite(v):return None
    return float(v)
def odds_delta(a,b):
    if not isinstance(a,list) or not isinstance(b,list) or len(a)!=len(b):
        return None
    if any(n(x) is None for x in a+b):return None
    return [round(float(y)-float(x),5) for x,y in zip(a,b)]
def evidence_changes(previous,latest):
    old=previous.get("evidence") or {}
    new=latest.get("evidence") or {}
    out=[]
    def emit(kind,before,after):
        if before is not None and after is not None and before!=after:
            out.append({"kind":kind,"before":before,"after":after})
    if old and new:
        emit("INJURY_REPORT_STATE",old.get("injury_report_state"),new.get("injury_report_state"))
        emit("CONFIRMED_INJURY_PLAYER_IDS",old.get("verified_absence_ids"),new.get("verified_absence_ids"))
        om,nn=old.get("goal_expectation") or {},new.get("goal_expectation") or {}
        for side in ("home","away"):
            a,b=n(om.get(side)),n(nn.get(side))
            if a is not None and b is not None and abs(b-a)>1e-5:
                out.append({"kind":"MODEL_EXPECTED_GOALS_"+side.upper(),
                            "before":a,"after":b,"delta":round(b-a,5)})
        oa=(old.get("market_assimilation") or {}).get("applied_home_minus_away_goals_shift")
        na=(new.get("market_assimilation") or {}).get("applied_home_minus_away_goals_shift")
        if n(oa) is not None and n(na) is not None and abs(float(na)-float(oa))>1e-5:
            out.append({"kind":"007_ASIAN_COMPANIES_FUSION_MARGIN_SHIFT",
                        "before":oa,"after":na,"delta":round(float(na)-float(oa),5)})
    return out

def compare(current,history):
    R.check_bundle(current)
    R.require(current.get("sport")=="football","ONLY_FOOTBALL_CAPTURE_MOVEMENT")
    all_prev={}
    for b in history:
        R.check_bundle(b)
        R.require(b.get("sport")=="football","PREVIOUS_SPORT_MISMATCH")
        for item in b["records"]:
            all_prev.setdefault(str(item["match_id"]),[]).append(item)
    matched=0
    first=0
    flips=0
    rows=[]
    for g in current["records"]:
        mid=str(g["match_id"])
        t=R.stamp(g["generated_utc"])
        choices=[p for p in all_prev.get(mid,[])
                 if R.stamp(p["generated_utc"])<t]
        for p in choices:
            identity=("official_game_id","jc_number","home_team","away_team","home_id","away_id","kickoff_utc")
            R.require(all(p.get(k)==g.get(k) for k in identity),
                      "PREVIOUS_FOOTBALL_MATCH_IDENTITY_DRIFT")
        if not choices:
            first+=1
            rows.append({"match_id":mid,"jc_number":g.get("jc_number"),
                         "status":"FIRST_VERIFIED_OBSERVATION_NO_PREVIOUS_SNAPSHOT",
                         "current_capture_utc":g["capture_utc"],
                         "current_generated_utc":g["generated_utc"],
                         "has_valid_pregame_analysis":True,"changes":[]})
            continue
        prev=max(choices,key=lambda p:(R.stamp(p["generated_utc"]),R.stamp(p["capture_utc"]),int(p["run_id"])))
        matched+=1
        changes=[]
        for key in MARKETS:
            a=prev["markets"][key];b=g["markets"][key]
            old_direction,new_direction=direction(a,key),direction(b,key)
            if old_direction is not None and new_direction is not None and old_direction!=new_direction:
                if key=="hhad" and a.get("signed_home_handicap")!=b.get("signed_home_handicap"):
                    typ="OFFICIAL_JC_LINE_CHANGED_NOT_SAME_EVENT_DIRECTION_REVERSAL"
                else:
                    typ="MODEL_DIRECTION_REVERSED"
                    flips+=1
                changes.append({"market":key,"kind":typ,
                                "before":old_direction,"after":new_direction})
            if key=="hhad" and a.get("signed_home_handicap")!=b.get("signed_home_handicap"):
                changes.append({"market":key,"kind":"JC_HANDICAP_CHANGED",
                                "before":a.get("signed_home_handicap"),
                                "after":b.get("signed_home_handicap")})
            delta=odds_delta(a.get("jc_odds"),b.get("jc_odds"))
            if delta is not None and any(abs(z)>1e-7 for z in delta):
                changes.append({"market":key,"kind":"OFFICIAL_JC_ODDS_MOVED",
                                "old_odds":a["jc_odds"],"new_odds":b["jc_odds"],
                                "delta":delta})
            ap=a.get("probabilities") or {}
            bp=b.get("probabilities") or {}
            if isinstance(ap,dict) and isinstance(bp,dict):
                numeric={label:round(float(bp[label])-float(ap[label]),6)
                         for label in ap if label in bp
                         and n(ap[label]) is not None and n(bp[label]) is not None}
                if any(abs(z)>1e-7 for z in numeric.values()):
                    changes.append({"market":key,"kind":"MODEL_PROBABILITY_MOVEMENT_PP",
                                   "percentage_point_change":{k:round(v*100,4) for k,v in numeric.items()}})
        changes+=evidence_changes(prev,g)
        rows.append({"match_id":mid,"jc_number":g.get("jc_number"),
                     "status":"ASOF_MOVEMENT_COMPUTED_FROM_IMMUTABLE_PREGAME_EVIDENCE",
                     "previous_capture_utc":prev["capture_utc"],
                     "current_capture_utc":g["capture_utc"],
                     "previous_generated_utc":prev["generated_utc"],
                     "current_generated_utc":g["generated_utc"],
                     "previous_source_sha256":prev["source_snapshot_sha256"],
                     "current_source_sha256":g["source_snapshot_sha256"],
                     "changes":changes})
    return {"schema_version":VERSION,"sport":"football",
        "current_bundle_sha256":current["bundle_sha256"],
        "verified_games":len(current["records"]),
        "compared_games":matched,"first_observations":first,
        "model_direction_reversals":flips,
        "games":rows,
        "no_previous_snapshot_is_valid":True,
        "not_an_accuracy_calibration_or_postgame_training":True,
        "current_source_is_immutable_sha_verified":True}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--current",required=True)
    ap.add_argument("--history-dir")
    ap.add_argument("--out",required=True)
    args=ap.parse_args()
    current=json.loads(Path(args.current).read_text(encoding="utf-8"))
    previous=[]
    if args.history_dir:
        for f in sorted(Path(args.history_dir).rglob("*.json")):
            previous.append(json.loads(f.read_text(encoding="utf-8")))
    report=compare(current,previous)
    out=Path(args.out);out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("FOOTBALL_007_HOURLY_PRETIP_MOVEMENT",report["verified_games"],
          "compared",report["compared_games"],"first",report["first_observations"],
          "reversals",report["model_direction_reversals"])

if __name__=="__main__":main()
