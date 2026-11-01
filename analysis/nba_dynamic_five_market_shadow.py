#!/usr/bin/env python3
"""Point-in-time five-market probability shadow; production and delivery are immutable."""
from __future__ import annotations
import argparse, json, math
from datetime import datetime, timezone
from pathlib import Path

MARKETS=("JINGCAI_WIN","JINGCAI_HANDICAP","JINGCAI_TOTAL","CROWN_HANDICAP","CROWN_TOTAL")

def num(x):
    if x is None or isinstance(x,bool): return None
    try:
        y=float(x)
        return y if math.isfinite(y) else None
    except (TypeError,ValueError): return None

def stamp(x):
    try:
        d=datetime.fromisoformat(str(x).replace("Z","+00:00"))
        return d if d.tzinfo is not None else None
    except (TypeError,ValueError): return None

def iso(d):
    return d.astimezone(timezone.utc).isoformat() if d else None

def cdf(z):
    return 0.5*(1.0+math.erf(z/math.sqrt(2.0)))

def side_probability(mu,sigma,threshold):
    mu,sigma,threshold=map(num,(mu,sigma,threshold))
    if None in (mu,sigma,threshold) or sigma<=0: return None
    return min(1.0,max(0.0,cdf((mu-threshold)/sigma)))

def index_rows(rows):
    out={}
    for row in rows or []:
        gid=str(row.get("game_id") or "")
        if not gid or gid in out: raise ValueError("DUPLICATE_OR_MISSING_GAME_ID")
        out[gid]=row
    return out

def _market_map(game):
    return game.get("markets") if isinstance(game.get("markets"),dict) else {}

def _jc_games(jingcai):
    feed=(jingcai or {}).get("jc_007_public_odds_shadow") or {}
    return feed,index_rows(feed.get("games",[]))

def _line_equal(a,b):
    x,y=num(a),num(b)
    return x is not None and y is not None and abs(x-y)<=1e-6

def _probability_record(key, direction, line, signed_home, margin, margin_sigma, total, total_sigma, home_ml, away_ml):
    if key=="JINGCAI_WIN":
        first,second=home_ml,away_ml
        first_name,second_name="HOME_WIN","AWAY_WIN"
    elif key.endswith("HANDICAP"):
        if signed_home is None:
            first=second=None
        else:
            first=side_probability(margin,margin_sigma,-signed_home)
            second=(1.0-first) if first is not None else None
        first_name,second_name="HOME_COVER","AWAY_COVER"
    else:
        first=side_probability(total,total_sigma,line)
        second=(1.0-first) if first is not None else None
        first_name,second_name="OVER","UNDER"
    candidate=None
    if first is not None and second is not None:
        if abs(first-second)<=1e-12: candidate="TIE"
        else: candidate=first_name if first>second else second_name
    candidate_p=(first if candidate==first_name else second if candidate==second_name else None)
    selected=(first if direction==first_name else second if direction==second_name else None)
    return {
        "first_side":first_name,"second_side":second_name,
        "first_side_probability":first,"second_side_probability":second,
        "home_win_probability":first if key=="JINGCAI_WIN" else None,
        "home_cover_probability":first if key.endswith("HANDICAP") else None,
        "away_cover_probability":second if key.endswith("HANDICAP") else None,
        "over_probability":first if key.endswith("TOTAL") else None,
        "under_probability":second if key.endswith("TOTAL") else None,
        "frozen_direction":direction,
        "frozen_direction_probability":selected,
        "candidate_direction":candidate,
        "candidate_direction_probability":candidate_p,
        "direction_agrees_with_frozen":bool(candidate==direction) if candidate not in (None,"TIE") and direction else None,
    }

def evaluate(joined, model, five, jingcai=None, consensus=None, injury=None, previous=None, slot=None):
    day=joined.get("requested_display_date")
    if five.get("target_date")!=day: raise ValueError("FROZEN_TARGET_DATE_MISMATCH")
    if model.get("target_display_date",model.get("target_date"))!=day: raise ValueError("MODEL_TARGET_DATE_MISMATCH")
    if (consensus or {}).get("target_date") not in (None,day): raise ValueError("CONSENSUS_TARGET_DATE_MISMATCH")
    if (jingcai or {}).get("target_date") not in (None,day): raise ValueError("JINGCAI_TARGET_DATE_MISMATCH")

    joined_games=index_rows([g for g in joined.get("nba_cba_games",[]) if g.get("league")=="NBA"])
    model_games=index_rows(model.get("games",model.get("game_predictions",[])))
    frozen_games=index_rows(five.get("games",[]))
    injury_games=index_rows((injury or {}).get("games",[]))
    jc_feed,jc_games=_jc_games(jingcai)
    consensus_games=index_rows((consensus or {}).get("games",[]))
    prev_games=index_rows((previous or {}).get("games",[]))

    board_capture=stamp(joined.get("captured_at_utc"))
    frozen_board_capture=stamp(five.get("board_capture_utc"))
    model_capture=stamp(model.get("generated_at_utc") or model.get("analysis_generated_at_utc"))
    model_capture_source="MODEL_REPORT_GENERATED_AT_UTC"
    if not model_capture:
        # Five-market forecast is generated only after the model artifact has
        # been produced and consumed; use its time as a conservative upper bound.
        model_capture=stamp(five.get("analysis_generated_at_utc"))
        model_capture_source="FIVE_MARKET_BUILD_UPPER_BOUND_MODEL_EXISTED_BY_THIS_TIME"
    five_capture=stamp(five.get("analysis_generated_at_utc"))
    if not board_capture or not frozen_board_capture or board_capture!=frozen_board_capture:
        raise ValueError("BOARD_CAPTURE_TIMESTAMP_MISMATCH")
    if not five_capture: raise ValueError("FIVE_MARKET_GENERATION_TIMESTAMP_MISSING")
    if not model_capture: raise ValueError("MODEL_GENERATION_TIMESTAMP_MISSING")
    if model_capture>five_capture: raise ValueError("MODEL_GENERATED_AFTER_FIVE_MARKET_FREEZE")
    if five_capture<board_capture: raise ValueError("FIVE_MARKET_BEFORE_BOARD_CAPTURE")
    if set(joined_games)!=set(frozen_games): raise ValueError("JOINED_FROZEN_GAME_SET_MISMATCH")

    rows=[]
    for gid,game in joined_games.items():
        frozen=frozen_games[gid]
        pred=model_games.get(gid,{})
        if not pred: raise ValueError("MODEL_GAME_MISSING:"+gid)
        identity=(game.get("home_team"),game.get("away_team"))
        if identity!=(frozen.get("home_team"),frozen.get("away_team")) or identity!=(pred.get("home_team"),pred.get("away_team")):
            raise ValueError("TEAM_IDENTITY_MISMATCH:"+gid)
        tip=stamp(game.get("start_time_beijing") or frozen.get("tipoff_beijing"))
        if not tip: raise ValueError("TIPOFF_TIMESTAMP_MISSING:"+gid)
        if stamp(frozen.get("tipoff_beijing"))!=tip: raise ValueError("TIPOFF_MISMATCH:"+gid)

        margin=num(pred.get("margin_mean_home_minus_away"))
        total=num(pred.get("total_mean"))
        margin_sigma=num(pred.get("margin_sigma"))
        total_sigma=num(pred.get("total_sigma"))
        ml=pred.get("model_probability") or {}
        home_ml,away_ml=num(ml.get("home")),num(ml.get("away"))
        model_status=pred.get("model_status",pred.get("status"))
        model_status_ok=model_status in ("OK","PARTIAL")
        distribution_ok=(model_status_ok and margin is not None and total is not None
                  and margin_sigma is not None and total_sigma is not None
                  and margin_sigma>0 and total_sigma>0)
        moneyline_ok=(model_status_ok and home_ml is not None and away_ml is not None
                  and 0<=home_ml<=1 and 0<=away_ml<=1
                  and abs(home_ml+away_ml-1.0)<=0.02)
        jc_game=jc_games.get(gid,{})
        jc_markets=jc_game.get("markets") or {}
        raw_markets=_market_map(game)
        frozen_markets=_market_map(frozen)
        previous_game=prev_games.get(gid,{})
        previous_markets=_market_map(previous_game)
        current={}
        for key in MARKETS:
            selection=frozen_markets.get(key) or {}
            frozen_direction=selection.get("direction")
            line=num(selection.get("line"))
            signed=num(selection.get("signed_home_handicap")) if key.endswith("HANDICAP") else None
            quote_capture=stamp(selection.get("captured_at_utc"))
            reasons=[]
            if not quote_capture: reasons.append("QUOTE_TIMESTAMP_MISSING")
            elif quote_capture>=tip: reasons.append("QUOTE_NOT_PRETIP")
            if board_capture>=tip: reasons.append("BOARD_NOT_PRETIP")
            if model_capture>=tip: reasons.append("MODEL_NOT_PRETIP")
            if five_capture>=tip: reasons.append("FIVE_MARKET_FORECAST_NOT_PRETIP")
            if quote_capture and quote_capture>five_capture:
                reasons.append("QUOTE_CAPTURE_AFTER_FIVE_MARKET_FREEZE")
            if not model_status_ok:
                reasons.append("INDEPENDENT_MODEL_STATUS_NOT_OK")
            source=selection.get("source")
            source_id=str(selection.get("source_id") or "")
            quote_freshness=selection.get("quote_freshness")

            if key.startswith("JINGCAI"):
                feed_market={"JINGCAI_WIN":"win_lose","JINGCAI_HANDICAP":"handicap","JINGCAI_TOTAL":"total"}[key]
                raw_item=jc_markets.get(feed_market) or {}
                raw_current=((raw_item.get("data") or {}).get("current") or {})
                if raw_item.get("status")!="OBSERVED":
                    reasons.append("JINGCAI_SOURCE_ROW_NOT_OBSERVED")
                if stamp(jc_feed.get("captured_at_utc"))!=quote_capture:
                    reasons.append("JINGCAI_CAPTURE_TIME_MISMATCH")
                if key=="JINGCAI_HANDICAP" and not _line_equal(line,raw_current.get("line")):
                    reasons.append("JINGCAI_HANDICAP_LINE_MISMATCH")
                if key=="JINGCAI_TOTAL" and not _line_equal(line,raw_current.get("line")):
                    reasons.append("JINGCAI_TOTAL_LINE_MISMATCH")
                if key=="JINGCAI_WIN" and line is not None:
                    reasons.append("JINGCAI_MONEYLINE_SHOULD_NOT_HAVE_LINE")
            else:
                if source_id!="3": reasons.append("CROWN_SOURCE_ID_NOT_3")
                kind="full_spread" if key=="CROWN_HANDICAP" else "full_total"
                raw_current=((raw_markets.get(kind) or {}).get("current") or {})
                # The joined board may expose a different default company line.
                # The frozen selection's exact ID3 provenance is authoritative;
                # never reject an ID3 quote merely because a non-ID3 joined line differs.
                if line is None:
                    reasons.append("CROWN_FROZEN_LINE_MISSING")
                if key=="CROWN_HANDICAP" and line is not None and signed is not None and abs(signed+line)>1e-6:
                    reasons.append("CROWN_HOME_HANDICAP_SIGN_MISMATCH")
                if key=="CROWN_TOTAL" and raw_current.get("line") is None and quote_freshness!="ARCHIVED_PRIOR_NOT_LIVE":
                    reasons.append("CROWN_CURRENT_TOTAL_QUOTE_MISSING")
            if key.endswith("HANDICAP") and (line is None or signed is None):
                reasons.append("HANDICAP_LINE_OR_SIGN_MISSING")
            if key=="JINGCAI_HANDICAP" and line is not None and signed is not None and abs(signed-line)>1e-6:
                reasons.append("JINGCAI_HOME_HANDICAP_SIGN_MISMATCH")
            if key.endswith("TOTAL") and line is None:
                reasons.append("TOTAL_LINE_MISSING")
            if selection.get("status") not in ("DIRECTION_ISSUED","NO_MODEL_EDGE_TIE","MISSING_MODEL_OR_LINE"):
                reasons.append("FROZEN_SELECTION_STATUS_"+str(selection.get("status") or "MISSING"))

            valid=not reasons
            market_model_ok=moneyline_ok if key=="JINGCAI_WIN" else distribution_ok
            if valid and market_model_ok:
                probs=_probability_record(key,frozen_direction,line,signed,margin,margin_sigma,total,total_sigma,home_ml,away_ml)
                probability_status="PRETIP_VALID"
            else:
                probs=_probability_record(key,frozen_direction,line,signed,margin,margin_sigma,total,total_sigma,home_ml,away_ml) if valid and market_model_ok else {
                    "first_side":"HOME_WIN" if key=="JINGCAI_WIN" else "HOME_COVER" if key.endswith("HANDICAP") else "OVER",
                    "second_side":"AWAY_WIN" if key=="JINGCAI_WIN" else "AWAY_COVER" if key.endswith("HANDICAP") else "UNDER",
                    "first_side_probability":None,"second_side_probability":None,
                    "home_win_probability":None,"home_cover_probability":None,"away_cover_probability":None,
                    "over_probability":None,"under_probability":None,"frozen_direction":frozen_direction,
                    "frozen_direction_probability":None,"candidate_direction":None,
                    "candidate_direction_probability":None,"direction_agrees_with_frozen":None}
                probability_status=("MODEL_DISTRIBUTION_MISSING" if valid else "INVALID_PRETIP_SOURCE")
            prev=(previous_markets.get(key) or {})
            prev_line=num(prev.get("line"))
            same_line=(key=="JINGCAI_WIN" or (line is not None and prev_line is not None and abs(line-prev_line)<=1e-6))
            prev_first=num(prev.get("first_side_probability"))
            delta=(round((probs["first_side_probability"]-prev_first)*100,3)
                   if same_line and prev_first is not None and probs["first_side_probability"] is not None else None)
            old_dir=prev.get("candidate_direction")
            old_candidate_p=num(prev.get("candidate_direction_probability"))
            candidate_delta=(round((probs["candidate_direction_probability"]-old_candidate_p)*100,3)
                if same_line and old_dir==probs.get("candidate_direction") and old_candidate_p is not None
                and probs.get("candidate_direction_probability") is not None else None)

            mc=selection.get("market_consensus") or {}
            price=mc.get("same_line_price_consensus") or {}
            consensus_capture=stamp(price.get("latest_source_capture_utc")
                or mc.get("market_price_latest_source_capture_utc")
                or mc.get("consensus_latest_source_capture_utc"))
            price_p=num(price.get("first_side_probability"))
            price_valid=(mc.get("direct_line_matches_price_reference") is True
                and price.get("status")=="AVAILABLE_SAME_LINE_MEDIAN"
                and price_p is not None and 0<=price_p<=1
                and consensus_capture is not None and consensus_capture<tip
                and consensus_capture<=five_capture)
            consensus_context={
                "status":mc.get("status"),"consensus_line":mc.get("consensus_line"),
                "company_count":mc.get("same_line_company_count"),
                "direct_line_matches_price_reference":mc.get("direct_line_matches_price_reference"),
                "first_side_probability":price_p if price_valid else None,
                "latest_source_capture_utc":iso(consensus_capture),
                "eligible_same_line_benchmark":price_valid,
                "fusion_applied":False}
            current[key]={
                **probs,"line":line,"signed_home_handicap":signed,
                "source":source,"source_id":source_id,"quote_capture_utc":iso(quote_capture),
                "quote_freshness":quote_freshness,
                "market_data_status":"PRETIP_VALID" if valid else "INVALID",
                "probability_status":probability_status,"invalid_reasons":reasons,
                "line_delta_points":round(line-prev_line,3) if line is not None and prev_line is not None else None,
                "first_side_probability_delta_pp_same_line":delta,
                "candidate_probability_delta_pp_same_line":candidate_delta,
                "candidate_direction_changed":(old_dir!=probs.get("candidate_direction")) if old_dir else None,
                "market_consensus":consensus_context,
                "consensus_capture_utc":iso(consensus_capture) if price_valid else None}
        injury_row=injury_games.get(gid) or pred.get("injury_context") or {}
        injury_capture=stamp(injury_row.get("source_captured_at_utc"))
        rows.append({
            "game_id":gid,"nba_game_id":game.get("nba_game_id"),
            "home_team":game.get("home_team"),"away_team":game.get("away_team"),
            "tipoff_beijing":game.get("start_time_beijing"),
            "board_capture_utc":iso(board_capture),"model_capture_utc":iso(model_capture),
            "model_capture_time_source":model_capture_source,
            "decision_asof_utc":iso(max([x for x in [board_capture,model_capture,five_capture]+[
                stamp(v.get("quote_capture_utc")) for v in current.values() if v.get("quote_capture_utc")]+[
                stamp(v.get("consensus_capture_utc")) for v in current.values() if v.get("consensus_capture_utc")]])),
            "model_version":pred.get("model_version"),
            "model_status":pred.get("model_status",pred.get("status")),
            "independent_model":{"home_win_probability":home_ml if moneyline_ok else None,
                "away_win_probability":away_ml if moneyline_ok else None,
                "margin_mean_home_minus_away":margin,"total_mean":total,
                "margin_sigma":margin_sigma,"total_sigma":total_sigma},
            "injury_context":{"quality":injury_row.get("quality","NOT_PROVIDED"),
                "source_capture_utc":iso(injury_capture),
                "capture_before_tip":bool(injury_capture and injury_capture<tip),
                "player_adjustment":injury_row.get("player_adjustment",pred.get("injury_adjustment",{}).get("status"))},
            "markets":current,
            "market_probability_fusion":"DISABLED_SHADOW_ONLY",
            "production_probability_changed":False})
    return {
        "schema_version":"nba-dynamic-five-market-shadow-v2",
        "target_date":day,"slot":slot,
        "captured_at_utc":iso(board_capture),"model_capture_utc":iso(model_capture),
        "five_market_freeze_utc":iso(five_capture),
        "model_capture_time_source":model_capture_source,
        "jingcai_feed_capture_utc":iso(stamp(jc_feed.get("captured_at_utc"))),
        "game_count":len(rows),"games":rows,
        "production_model_modified":False,"pushplus_enabled":False,
        "market_probability_fusion":"DISABLED",
        "validation_state":"RESEARCH_ONLY_PENDING_CHRONOLOGICAL_OOS"}

def self_test():
    day="2026-11-01"; capture="2026-10-31T10:00:00+00:00"
    joined={"requested_display_date":day,"captured_at_utc":capture,"crown_quote_captured_at_utc":capture,
      "nba_cba_games":[{"league":"NBA","game_id":"1","nba_game_id":"e1","home_team":"H","away_team":"A",
       "start_time_beijing":"2026-11-01T08:00:00+08:00","markets":{
        "full_spread":{"current":{"line":5.5}},"full_total":{"current":{"line":220}}}}]}
    model={"target_display_date":day,"generated_at_utc":"2026-10-31T10:01:00+00:00","games":[{
      "game_id":"1","home_team":"H","away_team":"A","model_status":"OK",
      "model_probability":{"home":.6,"away":.4},"margin_mean_home_minus_away":4,
      "total_mean":225,"margin_sigma":10,"total_sigma":15,"model_version":"test"}]}
    markets={
      "JINGCAI_WIN":{"status":"DIRECTION_ISSUED","direction":"HOME_WIN","line":None,"captured_at_utc":capture,"source":"007_JINGCAI"},
      "JINGCAI_HANDICAP":{"status":"DIRECTION_ISSUED","direction":"HOME_COVER","line":5.5,"signed_home_handicap":5.5,"captured_at_utc":capture,"source":"007_JINGCAI"},
      "JINGCAI_TOTAL":{"status":"DIRECTION_ISSUED","direction":"OVER","line":220,"captured_at_utc":capture,"source":"007_JINGCAI"},
      "CROWN_HANDICAP":{"status":"DIRECTION_ISSUED","direction":"AWAY_COVER","line":5.5,"signed_home_handicap":-5.5,"captured_at_utc":capture,"source":"007_CROWN_ID3","source_id":"3","quote_freshness":"CURRENT_CAPTURE"},
      "CROWN_TOTAL":{"status":"DIRECTION_ISSUED","direction":"OVER","line":220,"captured_at_utc":capture,"source":"007_CROWN_ID3","source_id":"3","quote_freshness":"CURRENT_CAPTURE"}}
    five={"target_date":day,"board_capture_utc":capture,
      "analysis_generated_at_utc":"2026-10-31T10:02:00+00:00",
      "games":[{"game_id":"1","nba_game_id":"e1",
      "home_team":"H","away_team":"A","tipoff_beijing":"2026-11-01T08:00:00+08:00","markets":markets}]}
    jc={"target_date":day,"jc_007_public_odds_shadow":{"captured_at_utc":capture,"games":[{
      "game_id":"1","markets":{
       "win_lose":{"status":"OBSERVED","data":{"current":{"first_side":1.7,"second_side":1.8}}},
       "handicap":{"status":"OBSERVED","data":{"current":{"line":5.5,"first_side":1.7,"second_side":1.8}}},
       "total":{"status":"OBSERVED","data":{"current":{"line":220,"first_side":1.7,"second_side":1.8}}}}}]}}
    injury={"games":[{"game_id":"1","quality":"PUBLISHED_LISTED","source_captured_at_utc":capture,"player_adjustment":"DISABLED_NOT_BACKTESTED"}]}
    out=evaluate(joined,model,five,jc,{},injury,slot="2130")
    row=out["games"][0]
    assert out["game_count"]==1 and row["markets"]["JINGCAI_WIN"]["market_data_status"]=="PRETIP_VALID"
    assert abs(row["markets"]["JINGCAI_HANDICAP"]["home_cover_probability"]-cdf(.95))<1e-8
    assert row["markets"]["CROWN_HANDICAP"]["candidate_direction"]=="AWAY_COVER"
    assert row["markets"]["CROWN_HANDICAP"]["away_cover_probability"]>0.5
    assert row["markets"]["JINGCAI_TOTAL"]["over_probability"]>0.5
    assert out["production_model_modified"] is False and out["pushplus_enabled"] is False
    assert row["decision_asof_utc"]=="2026-10-31T10:02:00+00:00"
    late_freeze=dict(five); late_freeze["analysis_generated_at_utc"]="2026-11-01T00:01:00+00:00"
    late_freeze_out=evaluate(joined,model,late_freeze,jc)
    assert all(m["market_data_status"]=="INVALID" for m in late_freeze_out["games"][0]["markets"].values())
    late_model=dict(model); late_model["games"]=[dict(model["games"][0],model_status="DISABLED")]
    disabled_out=evaluate(joined,late_model,five,jc)
    assert all(m["market_data_status"]=="INVALID" for m in disabled_out["games"][0]["markets"].values())
    future_quote=dict(five); future_markets=dict(markets)
    future_markets["CROWN_TOTAL"]={**markets["CROWN_TOTAL"],"captured_at_utc":"2026-10-31T10:03:00+00:00"}
    future_quote["games"]=[dict(five["games"][0],markets=future_markets)]
    future_quote_out=evaluate(joined,model,future_quote,jc)
    assert future_quote_out["games"][0]["markets"]["CROWN_TOTAL"]["market_data_status"]=="INVALID"
    bad=dict(joined); bad["nba_cba_games"]=[dict(joined["nba_cba_games"][0],home_team="WRONG")]
    try:evaluate(bad,model,five,jc)
    except ValueError as exc: assert "TEAM_IDENTITY" in str(exc)
    else:raise AssertionError("TEAM_IDENTITY_MISMATCH_NOT_CAUGHT")
    stale=dict(five); stale["games"]=[dict(five["games"][0],markets={**markets,
      "CROWN_TOTAL":{**markets["CROWN_TOTAL"],"captured_at_utc":"2026-11-01T00:01:00+00:00"}})]
    stale_out=evaluate(joined,model,stale,jc)
    assert stale_out["games"][0]["markets"]["CROWN_TOTAL"]["market_data_status"]=="INVALID"
    mismatch=dict(jc); mismatch["jc_007_public_odds_shadow"]={"captured_at_utc":capture,"games":[{
      "game_id":"1","markets":{"win_lose":{"status":"OBSERVED","data":{"current":{}}},
      "handicap":{"status":"OBSERVED","data":{"current":{"line":7.5}}},
      "total":{"status":"OBSERVED","data":{"current":{"line":220}}}}}]}
    mismatch_out=evaluate(joined,model,five,mismatch)
    assert mismatch_out["games"][0]["markets"]["JINGCAI_HANDICAP"]["market_data_status"]=="INVALID"
    print("NBA_DYNAMIC_FIVE_MARKET_SHADOW_V2_SELFTEST_PASS")

def main():
    ap=argparse.ArgumentParser()
    for name in ("joined","model","five","jingcai","consensus","injury","previous","out","slot"):
        ap.add_argument("--"+name)
    ap.add_argument("--self-test",action="store_true")
    a=ap.parse_args()
    if a.self_test:return self_test()
    if not all((a.joined,a.model,a.five,a.jingcai,a.out)):raise SystemExit("REQUIRED_INPUT_MISSING")
    def load(path):
        return json.loads(Path(path).read_text(encoding="utf-8")) if path and Path(path).is_file() else {}
    try:
        result=evaluate(load(a.joined),load(a.model),load(a.five),load(a.jingcai),
                        load(a.consensus),load(a.injury),load(a.previous),a.slot)
    except Exception as exc:
        result={"schema_version":"nba-dynamic-five-market-shadow-v2",
          "status":"SHADOW_UNAVAILABLE","target_date":None,"slot":a.slot,
          "error_type":type(exc).__name__,"error":str(exc),
          "game_count":0,"games":[],"production_model_modified":False,
          "pushplus_enabled":False,"market_probability_fusion":"DISABLED",
          "validation_state":"RESEARCH_ONLY_PENDING_CHRONOLOGICAL_OOS"}
        print("DYNAMIC_FIVE_MARKET_SHADOW_UNAVAILABLE",type(exc).__name__,str(exc))
    Path(a.out).write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("DYNAMIC_FIVE_MARKET_SHADOW",result.get("status","OK_SHADOW"),result["game_count"],result["validation_state"])
if __name__=="__main__":main()
