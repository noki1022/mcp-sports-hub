#!/usr/bin/env python3
"""Grade ONLY the frozen 21:30 original pushed answer and independent shadow.

At no time regenerate model probabilities. The ONLY model input is archived
21:30 immutable branch content that was committed pretip. Real outcomes are
loaded in this separate postgame process, never by either prediction model.
"""
from __future__ import annotations
import argparse,hashlib,json,math,subprocess
from datetime import datetime,timezone
from pathlib import Path

KEYS=("JINGCAI_WIN","JINGCAI_HANDICAP","JINGCAI_TOTAL","CROWN_HANDICAP","CROWN_TOTAL")
SIDES={
 "JINGCAI_WIN":("HOME_WIN","AWAY_WIN"),
 "JINGCAI_HANDICAP":("HOME_COVER","AWAY_COVER"),
 "JINGCAI_TOTAL":("OVER","UNDER"),
 "CROWN_HANDICAP":("HOME_COVER","AWAY_COVER"),
 "CROWN_TOTAL":("OVER","UNDER")}
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def dt(x):
    try:
        t=datetime.fromisoformat(str(x).replace("Z","+00:00"))
        return t.astimezone(timezone.utc) if t.tzinfo else None
    except (TypeError,ValueError):return None
def finite(x):
    if isinstance(x,bool) or x is None:return None
    try:
        v=float(x)
        return v if math.isfinite(v) else None
    except (TypeError,ValueError):return None
def load(path):return json.loads(Path(path).read_text())
def index(rows):
    out={}
    for x in rows:
        k=str(x.get("game_id") or "")
        if not k or k in out:raise ValueError("DUPLICATED_SCORE_OR_FROZEN_ID")
        out[k]=x
    return out

def verify_lock(root,day):
    root=Path(root)
    path=root/"reports/dual-model-slot-lock"/day/"2130"
    proof=load(path/"seal.json")
    if (proof.get("schema_version")!="nba-dual-model-2130-independent-seal-v1"
            or proof.get("target_date")!=day or proof.get("slot")!="2130"
            or proof.get("is_authoritative_final_exam") is not True
            or proof.get("both_model_answers_are_separately_frozen") is not True):
        raise ValueError("NO_UNIQUE_AUTHENTIC_2130_DUAL_FINAL")
    for filename,expected in proof["sha256"].items():
        if not (path/filename).is_file() or sha(path/filename)!=expected:
            raise ValueError("ORIGINAL_OR_SHADOW_FINAL_FILE_WAS_MODIFIED:"+filename)
    orig=load(path/"original_2130_five_market_forecast.json")
    cand=load(path/"independent_prediction.json")
    if any(x.get("target_date")!=day for x in (orig,cand)):
        raise ValueError("FROZEN_ORIGINAL_SHADOW_BOARD_DIFFER")
    if orig.get("game_count")!=len(cand.get("games",[])):
        raise ValueError("FINAL_ORIGINAL_SHADOW_GAME_COUNTS_DIFFER")
    if len(cand.get("games",[]))<1:
        raise ValueError("EMPTY_FROZEN_2130_EXAM")
    original=index(orig.get("games",[]))
    shadow=index(cand["games"])
    if set(original)!=set(shadow):
        raise ValueError("DIFFERENT_FINAL_ORIGINAL_AND_SHADOW_GAME_IDS")
    first_tip=min(dt(g["tipoff_beijing"]) for g in cand["games"])
    model_t=dt(proof["shadow_generated_at_utc"])
    lock_t=dt(proof["first_successful_archive_at_utc"])
    if not first_tip or not model_t or not lock_t or not model_t<=lock_t<first_tip:
        raise ValueError("FINAL_WAS_NOT_COMMITTED_BEFORE_NBA_TIP")
    # Source time and Github commit time are independent immutable evidence.
    manifest=load(path/"input_manifest.json")
    if manifest.get("archive_slot_is_21:30_final") is not True or (
            manifest.get("original_model_output_never_mounted") is not True):
        raise ValueError("SHADOW_DID_NOT_ANALYZE_INDEPENDENTLY")
    original_run=load(path/"original_pushplus_marker.json")
    if (str(original_run.get("run_id"))!=str(proof.get("original_production_push_run_id"))
            or original_run.get("state")!="API_ACCEPTED_NOT_DEVICE_CONFIRMED"):
        raise ValueError("ORIGINAL_2130_FORECAST_NEVER_ACCEPTED_FOR_PUSHPLUS")
    # GitHub history must contain a separate branch commit that actually
    # established this particular final forecast *before* kickoff. JSON time
    # metadata alone is self-declared and insufficient.
    relative=str((path/"seal.json").relative_to(root))
    cmd=subprocess.run(["git","log","-1","--format=%H %cI","--",relative],
                       cwd=root,capture_output=True,text=True,check=False)
    if cmd.returncode or not cmd.stdout.strip():
        raise ValueError("NO_PERSISTENT_GIT_COMMIT_FOR_FINAL_EXAM")
    commit_sha,commit_time=cmd.stdout.strip().split(maxsplit=1)
    if not dt(commit_time) or not dt(commit_time)<first_tip:
        raise ValueError("OFFICIAL_GIT_2130_ARCHIVE_COMMITTED_POST_TIP")
    return orig,cand,proof,{"git_final_archive_commit":commit_sha,
                             "first_tipoff":first_tip.isoformat(),
                             "shadow_generated_at":model_t.isoformat(),
                             "sealing_completed_at":lock_t.isoformat(),
                             "original_pushed_preview_sha256":proof["sha256"][
                                "original_2130_pushed_iphone.html"]}

def score(orig,cand,proof,settlement):
    if settlement.get("schema_version")!="nba-five-market-settlement-v1" or (
            settlement.get("beijing_date")!=orig.get("target_date")):
        raise ValueError("FINAL_SCORE_NOT_FROM_INDEPENDENT_OFFICIAL_SETTLEMENT")
    original=index(orig["games"]);shadow=index(cand["games"])
    scores=index(settlement["games"])
    by={k:[] for k in KEYS}
    probability_pairs={k:[] for k in KEYS}
    candidate_pairs={k:[] for k in KEYS}
    rejected={}
    for gid,g in original.items():
        s=shadow[gid];finished=scores.get(gid)
        if finished is None:
            rejected[gid]="NO_INDEPENDENT_OFFICIAL_FINAL";continue
        if (finished.get("home_team"),finished.get("away_team"))!=(
            g.get("home_team"),g.get("away_team")) or (
            s.get("home_team"),s.get("away_team"))!=(
            g.get("home_team"),g.get("away_team")):
            raise ValueError("HOME_AWAY_OR_007_GAME_ID_DIVERGED")
        hp,ap=finished.get("home_points"),finished.get("away_points")
        if not isinstance(hp,int) or not isinstance(ap,int) or hp<40 or ap<40:
            rejected[gid]="NO_INDEPENDENT_VERIFIED_COMPLETED_SCORE";continue
        for key in KEYS:
            a=(g.get("markets") or {}).get(key) or {}
            b=(s.get("markets") or {}).get(key) or {}
            olddir,newdir=a.get("direction"),b.get("direction")
            if a.get("status")!="DIRECTION_ISSUED" or olddir not in SIDES[key] or (
                newdir not in (*SIDES[key], "TIE")):
                continue
            orig_line=finite(a.get("line"));new_line=finite(b.get("line"))
            orig_signed=finite(a.get("signed_home_handicap"));new_signed=finite(
                b.get("signed_home_handicap"))
            if (orig_line is None)!=(new_line is None) or (
                orig_line is not None and abs(orig_line-new_line)>1e-7):
                continue
            if key.endswith("HANDICAP") and (orig_signed is None or new_signed is None
                or abs(orig_signed-new_signed)>1e-7):
                continue
            p=finite(b.get("first_side_probability"))
            p0=finite(a.get("model_direction_probability"))
            if p is None or p0 is None or not 0<p<1 or not 0<p0<1:
                continue
            if key=="JINGCAI_WIN":value=hp-ap
            elif key.endswith("HANDICAP"):value=hp-ap+orig_signed
            else:value=hp+ap-orig_line
            if abs(value)<1e-7:continue
            y=int(value>0)
            po=p0 if olddir==SIDES[key][0] else 1-p0
            expected=SIDES[key][0] if p>.5 else SIDES[key][1] if p<.5 else "TIE"
            if newdir != expected:
                raise ValueError("SHADOW_PROBABILITY_DIRECTION_CONFLICT")
            pair={
                "game_id":gid,"model_line":orig_line,
                "signed_home_handicap":orig_signed,
                "final_home_points":hp,"final_away_points":ap,
                "actual_first_side":y,
                "original_direction":olddir,
                "shadow_direction":newdir,
                "original_hit":int(olddir==SIDES[key][1-y]),
                "shadow_hit":int(newdir==SIDES[key][1-y]) if newdir!="TIE" else None,
                "original_first_side_probability":po,
                "shadow_first_side_probability":p,
                "original_brier":(po-y)**2,
                "shadow_brier":(p-y)**2,
                "original_log_loss":-math.log(po if y else 1-po),
                "shadow_log_loss":-math.log(p if y else 1-p)}
            probability_pairs[key].append(pair)
            if newdir != "TIE":
                by[key].append(pair)
            research=((s.get("research_model_candidates") or {}).get(
                "ROBUST_MULTIBOOK") or {}).get(key)
            if research is not None:
                if research.get("market")!=key or (
                    research.get("line")!=b.get("line") or
                    research.get("signed_home_handicap")!=b.get("signed_home_handicap")):
                    raise ValueError("RESEARCH_MULTIBOOK_SCORE_LINE_OR_SIDE_CHANGED")
                q=finite(research.get("first_side_probability"))
                if q is not None and 0<q<1:
                    expected=SIDES[key][0] if q>.5 else SIDES[key][1] if q<.5 else "TIE"
                    if expected!=research.get("direction"):
                        raise ValueError("RESEARCH_MULTIBOOK_PROBABILITY_DIRECTION_CONFLICT")
                    if expected!="TIE":
                        candidate_pairs[key].append({
                            "game_id":gid,"same_line_as_original_and_shadow":True,
                            "original_hit":int(olddir==SIDES[key][1-y]),
                            "shadow_baseline_hit":int(newdir==SIDES[key][1-y]) if newdir!="TIE" else None,
                            "multibook_candidate_hit":int(expected==SIDES[key][1-y]),
                            "original_brier":(po-y)**2,
                            "shadow_baseline_brier":(p-y)**2,
                            "multibook_candidate_brier":(q-y)**2,
                        })
    final={}
    for k,v in by.items():
        count=len(v)
        def avg(field):
            return round(sum(x[field] for x in v)/count,7) if count else None
        final[k]={"paired_graded":count,
                  "original_hits":sum(x["original_hit"] for x in v),
                  "shadow_hits":sum(x["shadow_hit"] for x in v),
                  "original_hit_rate":avg("original_hit"),
                  "shadow_hit_rate":avg("shadow_hit"),
                  "original_brier":avg("original_brier"),
                  "shadow_brier":avg("shadow_brier"),
                  "shadow_minus_original_brier":(
                      round(avg("shadow_brier")-avg("original_brier"),7)
                      if count else None),
                  "game_score_pairs":v}
    trial={}
    for key,v in candidate_pairs.items():
        count=len(v)
        def avg(name):
            valid=[r[name] for r in v if r[name] is not None]
            return round(sum(valid)/len(valid),8) if valid else None
        trial[key]={
            "same_game_line_paired_n":count,
            "original_hits":sum(r["original_hit"] for r in v),
            "independent_shadow_baseline_hits":sum(r["shadow_baseline_hit"] or 0 for r in v),
            "multibook_candidate_hits":sum(r["multibook_candidate_hit"] for r in v),
            "shadow_baseline_directional_n":sum(r["shadow_baseline_hit"] is not None for r in v),
            "original_brier":avg("original_brier"),
            "independent_shadow_baseline_brier":avg("shadow_baseline_brier"),
            "multibook_candidate_brier":avg("multibook_candidate_brier"),
            "precommitted_research_variant_not_live_promoted":True,
            "per_game_evidence":v,
        }
    return {"schema_version":"nba-exact-2130-two-model-scorecard-v1",
        "target_date":orig["target_date"],
        "source_final":"ORIGINAL_PUSHED_2130_AND_INDEPENDENT_SHADOW_2130_ONLY",
        "five_market_by_market":final,
        "probability_pairs_including_neutral":probability_pairs,
        "neutral_probabilities_are_scored_not_discarded":True,
        "multibook_research_candidate_paired_vs_original_and_shadow":trial,
        "candidate_is_not_official_second_model_answer":True,
        "independent_games_with_any_pair":len(set(
            x["game_id"] for market in by.values() for x in market)),
        "unscored_games":rejected,
        "no_backfilled_reconstruction":True,
        "no_postgame_input_ever_passed_to_prediction":True,
        "not_18_or_00_30_or_03_30_model_scores":True,
        "production_predictions_not_changed":True}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--ledger-worktree",required=True)
    p.add_argument("--settlement",required=True)
    p.add_argument("--day",required=True)
    p.add_argument("--out",required=True)
    a=p.parse_args()
    orig,cand,proof,commit=verify_lock(a.ledger_worktree,a.day)
    result=score(orig,cand,proof,load(a.settlement))
    result["git_lock_evidence"]=commit
    Path(a.out).write_text(json.dumps(result,indent=2,ensure_ascii=False,sort_keys=True)+"\n")
    print("NBA_2130_INDEPENDENT_DUAL_MODEL_FINAL_EXAM_GRADED",a.day,
          result["independent_games_with_any_pair"],
          {k:{"n":v["paired_graded"],"original_hits":v["original_hits"],
              "shadow_hits":v["shadow_hits"]} for k,v in result["five_market_by_market"].items()})
if __name__=="__main__":main()

