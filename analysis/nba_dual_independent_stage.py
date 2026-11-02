#!/usr/bin/env python3
"""Stage exact safe shared 007 market inputs for independent shadow per capture.

No original model probability, five-market forecast, historical scored games,
or completed game labels are ever copied. Stage directory is separate from
the repo and intended exclusively for network-disabled read-only Docker.
"""
from __future__ import annotations
from datetime import datetime,timezone,timedelta,time
from zoneinfo import ZoneInfo
BJ=ZoneInfo('Asia/Shanghai')
from pathlib import Path
import argparse,hashlib,json,os,re

VALID_SLOTS={"1200","1400","1500","1800","2100","2130","0030","0330"}
SCHEMA="nba-independent-dual-shadow-source-only-v1"
def dt(x):
    try:
        d=datetime.fromisoformat(str(x).replace("Z","+00:00"))
        return d.astimezone(timezone.utc) if d.tzinfo else None
    except (ValueError,TypeError):return None
def load(path):
    return json.loads(Path(path).read_text())
def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def deny(obj):
    blocked={"home_points","away_points","home_score","away_score","final_score_home",
    "final_score_away","observed_home_win","outcome","settlement","results","game_result",
    "winner","is_winner","score_observed_at_utc","outcome_label","finalized_at",
    "original_direction","model_probability","model_margin_home_minus_away"}
    def inner(x,depth=0):
        if depth>30:raise ValueError("UNBOUNDED_INPUT_JSON")
        if isinstance(x,dict):
            for k,v in x.items():
                if str(k).lower() in blocked:raise ValueError("SCORE_OR_OTHER_MODEL_FIELD_LEAK:"+str(k))
                inner(v,depth+1)
        elif isinstance(x,list):
            for v in x:inner(v,depth+1)
    inner(obj)

def strip_joined(raw):
    games=[]
    for g in raw.get("nba_cba_games",[]):
        if g.get("league")!="NBA":continue
        markets={}
        for name in ("full_spread","full_total"):
            m=(g.get("markets") or {}).get(name) or {}
            v=((m.get("current") or {}).get("line"))
            markets[name]={"current":{"line":v}}
        games.append({k:g.get(k) for k in ("game_id","nba_game_id","home_team","away_team","league","start_time_beijing")}|{"markets":markets})
    return {"requested_display_date":raw.get("requested_display_date"),
            "captured_at_utc":raw.get("captured_at_utc"),"nba_cba_games":games}
def strip_consensus(raw):
    games=[]
    for g in raw.get("games",[]):
        markets={}
        for name in ("full_spread","full_total"):
            m=(g.get("markets") or {}).get(name) or {}
            quotes=[{k:q.get(k) for k in ("company_id","line","source_capture_utc",
                      "excluded_as_line_outlier")} for q in m.get("quotes",[])]
            markets[name]={"status":m.get("status"),
                           "median_line":m.get("median_line"),
                           "effective_company_count":m.get("effective_company_count"),
                           "quotes":quotes}
        games.append({k:g.get(k) for k in (
            "game_id","nba_game_id","home_team","away_team","tipoff_beijing")}|{"markets":markets})
    return {"target_date":raw.get("target_date"),
            "collection_completed_at_utc":raw.get("collection_completed_at_utc"),
            "games":games}
def strip_jc(raw):
    f=raw.get("jc_007_public_odds_shadow") or {}
    games=[]
    for g in f.get("games",[]):
        markets={}
        for k in ("win_lose","handicap","total"):
            m=(g.get("markets") or {}).get(k) or {}
            current=(m.get("data") or {}).get("current") or {}
            markets[k]={"status":m.get("status"),
                        "data":{"current":{k:current.get(k) for k in (
                            "line","first_side","second_side")}}}
        games.append({k:g.get(k) for k in (
            "game_id","nba_game_id","home_team","away_team")}|{"markets":markets})
    return {"target_date":raw.get("target_date"),
            "jc_007_public_odds_shadow":{"captured_at_utc":f.get("captured_at_utc"),
                                          "games":games}}

def marker(repo,run_id):
    matches=[]
    for path in (Path(repo)/"reports/pushplus-sent").glob("*/*.json"):
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}",path.parent.name):
            continue
        try:
            doc=load(path)
        except (OSError,ValueError):
            continue
        if str(doc.get("run_id"))==str(run_id) and doc.get("state")=="API_ACCEPTED_NOT_DEVICE_CONFIRMED":
            if path.stem in VALID_SLOTS:matches.append((path.parent.name,path.stem,path))
    if not matches:raise ValueError("SKIP_NO_CANONICAL_ORIGINAL_ACCEPTED_MARKER")
    if len(matches)>1:raise ValueError("AMBIGUOUS_DUPLICATE_ORIGINAL_ACCEPTED_MARKERS")
    return matches[0]

def select(repo,day,slot,now):
    folder=Path(repo)/"reports/daily"/day/slot
    if slot=="2130":
        name="titan007_priority_joined.json"
    else:name="titan007_three_joined.json"
    sources={"joined":folder/name,"consensus":folder/"nba_market_consensus.json",
             "jingcai":folder/"nba_jingcai_three_market.json"}
    if any(not p.is_file() or p.is_symlink() for p in sources.values()):
        raise ValueError("MISSING_CERTIFIED_ORIGINAL_RAW_CAPTURE")
    raw={k:load(v) for k,v in sources.items()}
    board=dt(raw["joined"].get("captured_at_utc"))
    cap=dt(raw["consensus"].get("collection_completed_at_utc"))
    jc_time=dt((raw["jingcai"].get("jc_007_public_odds_shadow") or {}).get("captured_at_utc"))
    if any(x is None or x>now for x in (board,cap,jc_time)):
        raise ValueError("INCOMPLETE_OR_FUTURE_PRETIP_SOURCE")
    if slot=="2130":
        scheduled=(datetime.fromisoformat(day).date()-timedelta(days=1))
        cap_local=cap.astimezone(BJ)
        if cap_local.date()!=scheduled or cap_local.time()<time(21,30):
            raise ValueError("SKIP_EARLY_OR_WRONG_DAY_2130_CAPTURE")
        if cap_local.time()>time(22,0):
            raise ValueError("SKIP_LATE_2130_CAPTURE_NOT_FINAL")
    if now-cap>__import__("datetime").timedelta(minutes=150):
        raise ValueError("SHADOW_CAPTURE_STALE_NOT_SUITABLE_FOR_SLOT")
    if raw["joined"].get("requested_display_date")!=day or any(
            raw[k].get("target_date")!=day for k in ("consensus","jingcai")):
        raise ValueError("SOURCE_BEIJING_DATE_MISMATCH")
    tips=[dt(g.get("start_time_beijing")) for g in raw["joined"].get("nba_cba_games",[])
          if g.get("league")=="NBA"]
    if not tips or any(t is None or t<=now for t in tips):
        raise ValueError("ONE_OR_MORE_NBA_GAMES_ALREADY_STARTED")
    available=[]
    root=Path(repo)/"reports/daily"/day
    for path in root.glob("*/nba_market_consensus.json"):
        if path==sources["consensus"] or path.is_symlink():continue
        try: cand=load(path);t=dt(cand.get("collection_completed_at_utc"))
        except (OSError,ValueError):continue
        if (t is not None and t<cap and cand.get("target_date")==day
                and t<=now):
            available.append((t,path,cand))
    available.sort(key=lambda x:(x[0],str(x[1])))
    if len({x[0] for x in available})!=len(available):
        raise ValueError("DUPLICATE_ARCHIVED_007_SNAPSHOT_CAPTURE_CLOCK")
    # Bounded chronological window; keep the same original capture-by-capture
    # paired company IDs, NOT a synthetic open/close price reconstruction.
    available=available[-18:]
    prev=available[-1] if available else None
    return sources,raw,prev[1] if prev else None,prev[2] if prev else None,available

def stage(repo,run_id,dest,now):
    day,slot,accepted=marker(repo,run_id)
    sources,raw,previous_path,older,available=select(repo,day,slot,now)
    target=Path(dest).resolve()
    base=Path(repo).resolve()
    if target==base or base in target.parents or (target.exists() and list(target.iterdir())):
        raise ValueError("STAGE_MUST_BE_EMPTY_OUTSIDE_PRODUCTION_REPOSITORY")
    target.mkdir(parents=True,exist_ok=True)
    safe={"joined":strip_joined(raw["joined"]),
          "consensus":strip_consensus(raw["consensus"]),
          "jingcai":strip_jc(raw["jingcai"])}
    if older:safe["previous"]=strip_consensus(older)
    safe["history"]=[strip_consensus(item) for _,_,item in available]
    for key,val in safe.items():
        deny(val)
        (target/(key+".json")).write_text(json.dumps(val,ensure_ascii=False,sort_keys=True)+"\n")
    src=base/"analysis/nba_independent_market_shadow.py"
    (target/"analysis").mkdir()
    (target/"analysis/nba_independent_market_shadow.py").write_bytes(src.read_bytes())
    signal_code=base/"analysis/nba_multibook_crossplay_signals.py"
    (target/"analysis/nba_multibook_crossplay_signals.py").write_bytes(signal_code.read_bytes())
    manifest={"schema_version":SCHEMA,"target_date":day,"slot":slot,
        "original_completed_workflow_id":str(run_id),
        "original_accepted_push_marker_sha256":sha(accepted),
        "source_captured_utc":raw["consensus"]["collection_completed_at_utc"],
        "original_sources_sha256":{k:sha(v) for k,v in sources.items()},
        "earlier_source_sha256":sha(previous_path) if previous_path else None,
        "independent_chronological_snapshots":[
            {"capture_utc":t.isoformat(),"sha256":sha(path)}
            for t,path,_ in available],
        "multibook_candidate_code_sha256":sha(signal_code),
        "sanitized_inputs_sha256":{k:sha(target/(k+".json")) for k in safe},
        "prediction_code_sha256":sha(src),
        "original_model_output_never_mounted":True,
        "postgame_result_files_never_mounted":True,
        "training_labels_never_mounted":True,
        "network_disabled_at_execution_required":True,
        "archive_slot_is_21:30_final":slot=="2130",
        "staged_at_utc":now.isoformat()}
    (target/"input_manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n")
    print("DUAL_INDEPENDENT_SHADOW_INPUT_STAGE",day,slot,len(safe),run_id)
    return manifest

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--run-id",required=True)
    p.add_argument("--stage",default="/tmp/dual-independent-stage")
    p.add_argument("--repo",default=".")
    a=p.parse_args()
    try:
        stage(a.repo,a.run_id,a.stage,datetime.now(timezone.utc))
    except ValueError as exc:
        code=str(exc)
        # Scheduled recovery runs frequently complete with success but
        # intentionally skip already accepted slots. Do not mistake those
        # for a new prediction. All unexpected integrity failures remain RED.
        if code in ("SKIP_NO_CANONICAL_ORIGINAL_ACCEPTED_MARKER",
                    "SHADOW_CAPTURE_STALE_NOT_SUITABLE_FOR_SLOT",
                    "ONE_OR_MORE_NBA_GAMES_ALREADY_STARTED",
                    "SKIP_EARLY_OR_WRONG_DAY_2130_CAPTURE",
                    "SKIP_LATE_2130_CAPTURE_NOT_FINAL"):
            print("NBA_INDEPENDENT_SHADOW_SAFE_SKIP",code)
            return
        raise
if __name__=="__main__":main()
