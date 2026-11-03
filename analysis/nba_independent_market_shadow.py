#!/usr/bin/env python3
"""INDEPENDENT market-based NBA three-play model. Never imports or reads the
original team's predictions, original five-market forecast, a result, or a
postgame settlement. Input consists exclusively of certified shared PRETIP
007 markets and a frozen research parameter file; output is separate.

Reference probabilities are a BASELINE, not claimed calibrated model lift.
All JC(3) / Crown ID3(2) direct line judgments are computed, even when
quotes are missing (then marked no_direct_quote, never invented).
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
from pathlib import Path
import hashlib,json,math
import nba_multibook_crossplay_signals as BOOK
import nba_shadow_injury_asof as INJ

SCHEMA="nba-independent-market-only-fiveplay-v1"
KEYS=("JINGCAI_WIN","JINGCAI_HANDICAP","JINGCAI_TOTAL","CROWN_HANDICAP","CROWN_TOTAL")
SIGMA_MARGIN=15.55
SIGMA_TOTAL=19.47
MIN_COMPANIES=3

def clock(v):
    if not isinstance(v,str): return None
    try:
        d=datetime.fromisoformat(v.replace("Z","+00:00"))
        return d.astimezone(timezone.utc) if d.tzinfo else None
    except ValueError:return None
def n(v):
    if isinstance(v,bool) or v is None:return None
    try:
        x=float(v)
        return x if math.isfinite(x) else None
    except (ValueError,TypeError):return None
def cdf(x):
    return max(.001,min(.999,.5*math.erfc(-x/math.sqrt(2.))))
def idx(rows):
    out={}
    for r in rows or []:
        key=str(r.get("game_id") or "")
        if not key or key in out:raise ValueError("DUPLICATE_OR_MISSING_GAME_ID")
        out[key]=r
    return out
def sha_bytes(data):
    return hashlib.sha256(data).hexdigest()
def quote_movement(previous,now,kind):
    missing={"direction":"UNKNOWN","same_book_count":0,"up":0,"down":0,
             "median_points_change":None,"not_a_cover_probability":True}
    if not previous or previous.get("status")!="CONSENSUS_AVAILABLE" or (
        now.get("status")!="CONSENSUS_AVAILABLE"):
        return missing
    old={str(r.get("company_id")):r for r in previous.get("quotes",[])
         if not r.get("excluded_as_line_outlier")}
    new={str(r.get("company_id")):r for r in now.get("quotes",[])
         if not r.get("excluded_as_line_outlier")}
    matched=[]
    for cid in sorted(set(old)&set(new)):
        a,b=old[cid],new[cid]
        ta,tb=clock(a.get("source_capture_utc")),clock(b.get("source_capture_utc"))
        x,y=n(a.get("line")),n(b.get("line"))
        if ta and tb and ta<tb and x is not None and y is not None:
            matched.append(y-x)
    if len(matched)<MIN_COMPANIES:
        return {**missing,"same_book_count":len(matched)}
    up=sum(d>0 for d in matched);down=sum(d<0 for d in matched)
    meanchange=n(now.get("median_line"))-n(previous.get("median_line"))
    if not math.isfinite(meanchange):return missing
    direction=("RISING" if meanchange>0 and up>=MIN_COMPANIES and
               up/len(matched)>=.6 else "FALLING" if meanchange<0 and
               down>=MIN_COMPANIES and down/len(matched)>=.6 else
               "STABLE" if up==down==0 else "MIXED")
    return {"direction":direction,"same_book_count":len(matched),
            "up":up,"down":down,"median_points_change":round(meanchange,3),
            "not_a_cover_probability":True}

def compute(joined,consensus,jc,previous,now,slot,history=None,injury=None,injury_history=None):
    # The scoring state and any other model output are absent from this API.
    day=str(joined.get("requested_display_date") or "")
    board=clock(joined.get("captured_at_utc"))
    market_clock=clock(consensus.get("collection_completed_at_utc"))
    jc_clock=clock((jc.get("jc_007_public_odds_shadow") or {}).get("captured_at_utc"))
    if (not day or consensus.get("target_date")!=day or jc.get("target_date")!=day
            or not board or not market_clock or not jc_clock
            or not board<=now or not market_clock<=now or not jc_clock<=now):
        raise ValueError("INDEPENDENT_INPUT_CAPTURE_DATE_OR_CLOCK_INVALID")
    games=idx([g for g in joined.get("nba_cba_games",[]) if g.get("league")=="NBA"])
    market=idx(consensus.get("games"))
    jc_rows=idx((jc.get("jc_007_public_odds_shadow") or {}).get("games"))
    earlier=idx(previous.get("games")) if previous else {}
    if injury is None:
        injury=INJ.stage(None,list(games.values()),day,now)
    if injury.get("target_date")!=day or injury.get("schema_version")!=INJ.SCHEMA:
        raise ValueError("SHADOW_INJURY_SOURCE_DATE_OR_SCHEMA_MISMATCH")
    if set(str(z.get("game_id")) for z in injury.get("games",[]))!=set(games):
        raise ValueError("SHADOW_INJURY_CONTEXT_GAME_SET_MISMATCH")
    if not games or set(games)!=set(market) or not set(jc_rows)<=set(games):
        raise ValueError("INDEPENDENT_BOARD_OR_PROVIDER_IDENTITY_MISMATCH")
    if previous and (previous.get("target_date")!=day
                     or not clock(previous.get("collection_completed_at_utc"))<market_clock):
        raise ValueError("PAST_SOURCE_SNAPSHOT_NOT_BEFORE_CURRENT")
    snapshots = (history if history is not None else ([previous] if previous else []))
    if not isinstance(snapshots,list) or len(snapshots)>BOOK.MAX_PAST_SNAPSHOTS:
        raise ValueError("MULTIBOOK_CAPTURE_HISTORY_INVALID_OR_UNBOUNDED")
    # Both models are isolated: candidate reads ONLY validated shared 007
    # odds history, never any original prediction or settled result.
    verified_times=[]
    for item in snapshots:
        if not isinstance(item,dict) or item.get("target_date")!=day:
            raise ValueError("MULTIBOOK_HISTORY_DATE_MISMATCH")
        ts=clock(item.get("collection_completed_at_utc"))
        if ts is None or not ts<market_clock or ts>now:
            raise ValueError("POSTTIP_OR_NONCHRONOLOGICAL_MULTIBOOK_SOURCE")
        verified_times.append(ts)
    if len(set(verified_times))!=len(verified_times):
        raise ValueError("DUPLICATE_CAPTURE_HISTORY_CLOCK")
    if verified_times!=sorted(verified_times):
        raise ValueError("UNSORTED_MULTIBOOK_CAPTURE_HISTORY")
    rows=[]
    for gid,g in sorted(games.items(),key=lambda p:(p[1].get("start_time_beijing",""),p[0])):
        m=market[gid];j=jc_rows.get(gid,{})
        if any(g.get(k)!=m.get(k) for k in ("nba_game_id","home_team","away_team")):
            raise ValueError("SHARED_PRETIP_GAME_ID_TEAM_ORDER_MISMATCH")
        tip=clock(g.get("start_time_beijing"))
        if not tip or not now<tip:
            raise ValueError("MODEL_OUTPUT_NOT_BEFORE_GAME_START")
        if m.get("tipoff_beijing")!=g.get("start_time_beijing"):
            # 007 matching clocks may differ only by redundant seconds.
            if clock(m.get("tipoff_beijing"))!=tip:
                raise ValueError("MARKET_TIP_AND_BOARD_TIP_INCONSISTENT")
        if j and any(j.get(k)!=g.get(k) for k in ("nba_game_id","home_team","away_team")):
            raise ValueError("JC_RAW_GAME_TEAM_ORDER_MISMATCH")
        sm=(m.get("markets") or {}).get("full_spread") or {}
        tm=(m.get("markets") or {}).get("full_total") or {}
        valid_spread=(sm.get("status")=="CONSENSUS_AVAILABLE" and
                       n(sm.get("median_line")) is not None and
                       int(sm.get("effective_company_count") or 0)>=MIN_COMPANIES)
        valid_total=(tm.get("status")=="CONSENSUS_AVAILABLE" and
                      n(tm.get("median_line")) is not None and
                      int(tm.get("effective_company_count") or 0)>=MIN_COMPANIES)
        mu_m=n(sm.get("median_line")) if valid_spread else None # raw 007 positive=HOME GIVES
        mu_t=n(tm.get("median_line")) if valid_total else None
        crown=(g.get("markets") or {})
        crownspread=n(((crown.get("full_spread") or {}).get("current") or {}).get("line"))
        crowntotal=n(((crown.get("full_total") or {}).get("current") or {}).get("line"))
        jmarkets=j.get("markets") or {}
        raw_jc_handicap=(jmarkets.get("handicap") or {})
        raw_jc_total=(jmarkets.get("total") or {})
        raw_jc_win=(jmarkets.get("win_lose") or {})
        jc_spread=n(((raw_jc_handicap.get("data") or {}).get("current") or {}).get("line")) if raw_jc_handicap.get("status")=="OBSERVED" else None
        jc_total=n(((raw_jc_total.get("data") or {}).get("current") or {}).get("line")) if raw_jc_total.get("status")=="OBSERVED" else None
        jc_win_present=raw_jc_win.get("status")=="OBSERVED"
        lines={
            "JINGCAI_WIN":(None,None,jc_win_present),
            "JINGCAI_HANDICAP":(jc_spread,jc_spread,jc_spread is not None),
            "JINGCAI_TOTAL":(jc_total,None,jc_total is not None),
            "CROWN_HANDICAP":(crownspread,-crownspread if crownspread is not None else None,crownspread is not None),
            "CROWN_TOTAL":(crowntotal,None,crowntotal is not None),
        }
        predictions={}
        for key,(line,signed,has_quote) in lines.items():
            if key=="JINGCAI_WIN":
                p=cdf(mu_m/SIGMA_MARGIN) if mu_m is not None else None
                truefirst="HOME_WIN";truesecond="AWAY_WIN"
            elif key.endswith("HANDICAP"):
                p=cdf((mu_m+signed)/SIGMA_MARGIN) if mu_m is not None and signed is not None else None
                truefirst="HOME_COVER";truesecond="AWAY_COVER"
            else:
                p=cdf((mu_t-line)/SIGMA_TOTAL) if mu_t is not None and line is not None else None
                truefirst="OVER";truesecond="UNDER"
            direction=(truefirst if p is not None and p>.5 else
                       truesecond if p is not None and p<.5 else
                       "TIE" if p is not None else None)
            predictions[key]={
                "market":key,"line":line,"signed_home_handicap":signed,
                "first_side_probability":round(p,9) if p is not None else None,
                "direction":direction,
                "direct_quote_available":has_quote,
                "source_quality":"ASOF_DIRECT" if has_quote and p is not None else "DATA_UNAVAILABLE",
                "independent_model_source":"007_MULTI_BOOK_MARGIN_TOTAL_BASELINE",
                "model_probability_not_original_model_output":True,
            }
        oldmarkets=(earlier.get(gid) or {}).get("markets") or {}
        trends={
            "home_strength":quote_movement(oldmarkets.get("full_spread"),sm,"full_spread"),
            "expected_points":quote_movement(oldmarkets.get("full_total"),tm,"full_total")}
        multibook,provisional=BOOK.candidates_for_game(
            gid,m,snapshots,market_clock,predictions,predictions)
        # Independent baseline remains authoritative until *strictly*
        # future-frozen 21:30 results establish that this research variant
        # actually improves SAME-GAME/SAME-LINE directional decisions.
        injury_observed=INJ.features(injury,injury_history,gid,now,tip)
        rows.append({"game_id":gid,"nba_game_id":g.get("nba_game_id"),
           "jingcai_number":(j.get("jingcai_number") or None),
           "home_team":g.get("home_team"),"away_team":g.get("away_team"),
           "tipoff_beijing":tip.isoformat(),"markets":predictions,
           "research_multibook_features":multibook,
           "research_official_injury_asof":injury_observed,
           "research_model_candidates":{"ROBUST_MULTIBOOK":provisional},
           "market_strength_features":{"expected_home_margin":mu_m,
             "expected_total_points":mu_t,"paired_book_trends":trends,
             "independence_note":"MARKET_ONLY_NO_ORIGINAL_TEAM_FORECAST_INPUT"}})
    return {"schema_version":SCHEMA,"target_date":day,"slot":slot,
            "generated_at_utc":now.isoformat(),
            "last_shared_quote_capture_utc":market_clock.isoformat(),
            "games":rows,"game_count":len(rows),
            "three_plays":["moneyline","handicap","totals"],
            "multibook_candidate_version":BOOK.SCHEMA,
            "multibook_candidate_numerically_separate_not_promoted":True,
            "multibook_paired_sources_used":len(snapshots),
            "five_target_markets":list(KEYS),
            "model_provenance":"SELF_CONTAINED_MARKET_PRIOR_NOT_VALIDATED_TEAM_MODEL_UPLIFT",
            "assumed_margin_sigma":SIGMA_MARGIN,
            "assumed_total_sigma":SIGMA_TOTAL,
            "probability_uncertainty":"RESEARCH_ONLY_PROVISIONAL_SIGMAS_REQUIRE_OOS_CALIBRATION",
            "official_injury_feature_version":INJ.SCHEMA,
            "official_injury_is_observational_and_no_numeric_probability_uplift":True,
            "original_model_inputs_read":False,
            "postgame_data_read":False,
            "may_send_pushplus":False,
            "may_modify_production_probability":False}

def main():
    p=argparse.ArgumentParser()
    for k in ("joined","consensus","jingcai","out"):
        p.add_argument("--"+k,required=True)
    p.add_argument("--previous")
    p.add_argument("--history")
    p.add_argument("--injury")
    p.add_argument("--injury-history")
    p.add_argument("--slot",required=True)
    a=p.parse_args()
    args={k:Path(getattr(a,k)) for k in ("joined","consensus","jingcai")}
    prev=Path(a.previous) if a.previous else None
    source_hash={k:sha_bytes(path.read_bytes()) for k,path in args.items()}
    if prev:source_hash["previous"]=sha_bytes(prev.read_bytes())
    history_file=Path(a.history) if a.history else None
    if history_file:source_hash["history"]=sha_bytes(history_file.read_bytes())
    injury_file=Path(a.injury) if a.injury else None
    injury_history_file=Path(a.injury_history) if a.injury_history else None
    if injury_file:source_hash["injury"]=sha_bytes(injury_file.read_bytes())
    if injury_history_file:source_hash["injury_history"]=sha_bytes(injury_history_file.read_bytes())
    history=json.loads(history_file.read_text()) if history_file else None
    obj=compute(*(json.loads(path.read_text()) for path in args.values()),
                json.loads(prev.read_text()) if prev else None,
                datetime.now(timezone.utc),a.slot,history=history,
                injury=json.loads(injury_file.read_text()) if injury_file else None,
                injury_history=json.loads(injury_history_file.read_text()) if injury_history_file else None)
    obj["input_sha256"]=source_hash
    Path(a.out).write_text(json.dumps(obj,ensure_ascii=False,indent=2,sort_keys=True)+"\n")
    print("INDEPENDENT_SHADOW_NEW_PREDICTION_FROZEN",obj["target_date"],obj["slot"],obj["game_count"])
if __name__=="__main__":main()
