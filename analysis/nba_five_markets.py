#!/usr/bin/env python3
"""Five mandatory, independently tracked NBA research selections.

Markets:
 JINGCAI_WIN, JINGCAI_HANDICAP, JINGCAI_TOTAL, CROWN_HANDICAP, CROWN_TOTAL.
Read only the actual 007 Jingcai feed and 007 id=3 Crown/Crow* institutional
snapshot; NEVER average bookmaker lines into the Crown selection.
Selections are frozen with as-of source times for exact postgame scoring.

Crown/Crow* 007 feed line: + means HOME GIVES (home handicap = -line).
Jingcai: + means HOME RECEIVES (home handicap = +line).
Never cross-apply these sign conventions. Source-provenance and chronological
risk checks are separate from the desire to emit one observable direction.
"""
from __future__ import annotations
import argparse,json,math,re
from datetime import datetime,timezone
from pathlib import Path
from nba_market_consensus import selection_context

MARKETS=("JINGCAI_WIN","JINGCAI_HANDICAP","JINGCAI_TOTAL","CROWN_HANDICAP","CROWN_TOTAL")
LABELS={"JINGCAI_WIN":"竞彩胜负","JINGCAI_HANDICAP":"竞彩让分","JINGCAI_TOTAL":"竞彩大小分",
        "CROWN_HANDICAP":"皇冠让分","CROWN_TOTAL":"皇冠大小分"}

def n(x):
    try:
        if x is None or isinstance(x,bool):return None
        v=float(x)
        return v if math.isfinite(v) else None
    except (ValueError,TypeError):return None

def when(x):
    try:
        d=datetime.fromisoformat(str(x).replace("Z","+00:00"))
        return d if d.tzinfo is not None else None
    except (ValueError,TypeError):return None

def idx(rows):
    result={}
    for row in rows or []:
        k=str(row.get("game_id",""))
        if not k or k in result:raise ValueError("DUPLICATE_OR_MISSING_GAME_ID")
        result[k]=row
    return result

def jc_probability(market,direction,pred,line):
    """Model-derived directional probability; uncalibrated at an arbitrary line."""
    if market=="JINGCAI_WIN":
        home=n((pred.get("model_probability") or {}).get("home"))
        if home is None or not 0<=home<=1:return None
        return home if direction=="HOME_WIN" else 1-home
    kind="handicap" if market=="JINGCAI_HANDICAP" else "total"
    mu=n(pred.get("margin_mean_home_minus_away" if kind=="handicap" else "total_mean"))
    sigma=n(pred.get("margin_sigma" if kind=="handicap" else "total_sigma"))
    if None in (mu,sigma,line) or sigma<=0:return None
    threshold=-line if kind=="handicap" else line
    greater=.5*math.erfc((threshold-mu)/(math.sqrt(2)*sigma))
    return greater if direction in ("HOME_COVER","OVER") else 1-greater

def selection(market,diff,line,price=None,observed_at=None,source=None,status="OK",source_id=None):
    if status!="OK" or diff is None or (market!="JINGCAI_WIN" and line is None):
        return {"market":market,"status":status if status!="OK" else "MISSING_MODEL_OR_LINE",
                "direction":None,"line":line,"source":source,"source_id":source_id,
                "captured_at_utc":observed_at}
    # If prediction difference is exactly zero we cannot claim directional evidence.
    if abs(diff)<1e-9:
        return {"market":market,"status":"NO_MODEL_EDGE_TIE","direction":None,
                "line":line,"source":source,"source_id":source_id,"captured_at_utc":observed_at}
    if market=="JINGCAI_WIN":
        side=("HOME_WIN" if diff>0 else "AWAY_WIN")
    elif market in ("JINGCAI_HANDICAP","CROWN_HANDICAP"):
        side=("HOME_COVER" if diff>0 else "AWAY_COVER")
    else:side=("OVER" if diff>0 else "UNDER")
    return {"market":market,"status":"DIRECTION_ISSUED","direction":side,"line":line,
            "signed_home_handicap":(line if market=="JINGCAI_HANDICAP"
                 else -line if market=="CROWN_HANDICAP" else None),
            "model_minus_market":round(diff,4),"strength":"WEAK" if abs(diff)<2 else "RESEARCH",
            "source":source,"source_id":source_id,"captured_at_utc":observed_at,
            "note":"冻结研究方向；不等于经历史验证的投注优势"}

def make(joined,model,jc,top10,consensus=None):
    date=joined.get("requested_display_date")
    board=idx([g for g in joined.get("nba_cba_games",[]) if g.get("league")=="NBA"])
    preds=idx(model.get("games",[]))
    identity=(jc.get("jc_007_match_numbers") or {}).get("games") or {}
    feed=(jc.get("jc_007_public_odds_shadow") or {})
    prices=idx(feed.get("games",[]))
    institution=idx(top10.get("games",[]))
    consensus_rows=idx((consensus or {}).get("games",[]))
    capture=when(feed.get("captured_at_utc"))
    crown_source_id=str(joined.get("crown_source_id") or "")
    crown_capture_value=(joined.get("crown_quote_captured_at_utc")
                         or joined.get("captured_at_utc"))
    rows=[]
    for gid,g in board.items():
        tip=when(g.get("start_time_beijing"))
        label=(identity.get(gid) or {}).get("label")
        verified=((identity.get(gid) or {}).get("status")=="VERIFIED_JC_NUMBER"
                  and re.fullmatch(r"周[一二三四五六日天]\d{3}",str(label or "")) is not None)
        p=preds.get(gid,{})
        margin=n(p.get("margin_mean_home_minus_away")) if p.get("model_status") in ("OK","PARTIAL") else None
        total=n(p.get("total_mean")) if p.get("model_status") in ("OK","PARTIAL") else None
        # JC sale-number verification governs only the displayed number.
        # Market eligibility is anchored to exact 007 match ID and a pre-tip XML capture.
        jc_valid=bool(capture and tip and capture<tip and gid in prices)
        pools=(prices.get(gid) or {}).get("markets") or {}

        def jc_market(key,market):
            item=pools.get(key) or {}
            state=item.get("status","NO_QUOTE_IN_007_FEED")
            if state!="OBSERVED":
                return selection(market,None,None,status=state,source="007_JINGCAI")
            cur=(item.get("data") or {}).get("current") or {}
            line=n(cur.get("line"))
            if not jc_valid:
                return selection(market,None,line,status="JC_PRICE_TIME_OR_GAME_ID_UNVERIFIED",source="007_JINGCAI")
            first,second=n(cur.get("first_side")),n(cur.get("second_side"))
            if first is None or second is None or not (1<first<30 and 1<second<30):
                return selection(market,None,line,status="JC_INVALID_PRICE_PAIR",source="007_JINGCAI")
            if key=="win_lose":
                ans=selection(market,margin,None,observed_at=feed.get("captured_at_utc"),source="007_JINGCAI")
            else:
                if line is None:
                    return selection(market,None,None,status="INVALID_JC_LINE",source="007_JINGCAI")
                gap=(margin+line) if key=="handicap" and margin is not None else (
                     total-line if key=="total" and total is not None else None)
                ans=selection(market,gap,line,observed_at=feed.get("captured_at_utc"),source="007_JINGCAI")
            if ans["status"]=="DIRECTION_ISSUED":
                ans["model_direction_probability"]=jc_probability(market,ans["direction"],p,line)
                ans["raw_price_slots"]={"first":first,"second":second,
                    "orientation":"UNVERIFIED_RAW_FIRST_SECOND"}
            return ans

        selected={"JINGCAI_WIN":jc_market("win_lose","JINGCAI_WIN"),
                  "JINGCAI_HANDICAP":jc_market("handicap","JINGCAI_HANDICAP"),
                  "JINGCAI_TOTAL":jc_market("total","JINGCAI_TOTAL")}

        # Crown ID3 is already captured in the canonical joined board. Do not
        # re-fetch it from the separate institution-comparison path: that path
        # used only the target date and silently lost valid adjacent-date rows.
        # Archived ID3 evidence remains an explicit, non-live fallback only.
        im=(institution.get(gid) or {}).get("markets") or {}
        for kind,market in (("full_spread","CROWN_HANDICAP"),("full_total","CROWN_TOTAL")):
            direct_source_ok=(crown_source_id=="3"
                              and str(g.get("market_source_id") or "3")=="3")
            direct=(g.get("markets") or {}).get(kind) or {}
            quote=(direct.get("current") or {}) if direct_source_ok else {}
            line=n(quote.get("line"))
            quote_time=crown_capture_value
            source="007_CROWN_ID3"
            archived_fallback=False

            if line is None:
                candidates=[c for c in ((im.get(kind) or {}).get("companies") or [])
                    if str(c.get("company_id"))=="3"
                    and c.get("source")=="DATED_007_COMPANY_ID_ARCHIVED_PRETIP"]
                if len(candidates)==1:
                    archived=candidates[0]
                    archived_quote=archived.get("current") or {}
                    archived_line=n(archived_quote.get("line"))
                    archived_time=archived.get("observed_capture_utc")
                    if archived_line is not None:
                        line=archived_line
                        quote=archived_quote
                        quote_time=archived_time
                        source="007_CROWN_ID3_ARCHIVED_PRETIP"
                        archived_fallback=True

            if line is None:
                selected[market]=selection(market,None,None,source="007_CROWN_ID3",
                    status="CROWN_ID3_QUOTE_MISSING",source_id="3")
                continue
            actual_time=when(quote_time)
            if actual_time is None or tip is None or actual_time>=tip:
                selected[market]=selection(market,None,line,source=source,
                    status="CROWN_QUOTE_NOT_PRETIP",source_id="3")
                continue

            # Crown/Crow* raw positive line denotes HOME GIVES, so signed home
            # handicap is the negative of the source line.
            gap=((margin-line) if kind=="full_spread" and margin is not None else
                 (total-line) if kind=="full_total" and total is not None else None)
            selected[market]=selection(market,gap,line,source=source,source_id="3",
                observed_at=quote_time)
            selected[market]["quote_freshness"]=(
                "ARCHIVED_PRIOR_NOT_LIVE" if archived_fallback else "CURRENT_CAPTURE")
            selected[market]["raw_water_slots"]={
                "first_side":n(quote.get("first_side_water")),
                "second_side":n(quote.get("second_side_water")),
                "orientation":"UNVERIFIED_RAW_FIRST_SECOND"}
            if selected[market]["status"]=="DIRECTION_ISSUED":
                prob_market="JINGCAI_HANDICAP" if market=="CROWN_HANDICAP" else "JINGCAI_TOTAL"
                prob_line=-line if market=="CROWN_HANDICAP" else line
                selected[market]["model_direction_probability"]=jc_probability(
                    prob_market,selected[market]["direction"],p,prob_line)
                selected[market]["probability_status"]="MODEL_NORMAL_UNCALIBRATED_CROWN_ID3"

        # Multi-company consensus is an additional independent reference.
        # It never replaces the actual Jingcai or Crown ID3 quote and does not
        # alter the production model probability before chronological OOS proof.
        consensus_market=(consensus_rows.get(gid) or {}).get("markets") or {}
        direct_lines={
            "JINGCAI_WIN":None,
            "JINGCAI_HANDICAP":n((((pools.get("handicap") or {}).get("data") or {}).get("current") or {}).get("line")),
            "JINGCAI_TOTAL":n((((pools.get("total") or {}).get("data") or {}).get("current") or {}).get("line")),
            "CROWN_HANDICAP":selected["CROWN_HANDICAP"].get("line"),
            "CROWN_TOTAL":selected["CROWN_TOTAL"].get("line"),
        }
        for market in MARKETS:
            selected[market]["market_consensus"]=selection_context(
                market, direct_lines.get(market), selected[market].get("direction"),
                margin, total, n(p.get("margin_sigma")), n(p.get("total_sigma")),
                consensus_market)

        assert set(selected)==set(MARKETS)
        rows.append({"game_id":gid,"nba_game_id":g.get("nba_game_id"),
          "jingcai_number":label if verified else None,
          "jingcai_number_status":"VERIFIED" if verified else "UNVERIFIED_JC_LABEL",
          "home_team":g.get("home_team"),"away_team":g.get("away_team"),
          "tipoff_beijing":g.get("start_time_beijing"),
          "model_margin_home_minus_away":margin,"model_total":total,
          "markets":selected})
    return {"schema_version":"nba-five-markets-v1",
      "target_date":date,"board_capture_utc":joined.get("captured_at_utc"),
      "analysis_generated_at_utc":datetime.now(timezone.utc).isoformat(),
      "market_settlement_lock":"CAPTURED_PRETIP_ONLY",
      "crown_company_id":"3","crown_source":"007 ID3 (user-confirmed Crown)",
      "crown_identity_mapping":"USER_CONFIRMED_FIXED_MAPPING_ID3_EQUALS_CROWN",
      "market_consensus_source":"007_VALIDATED_COMPANY_IDS",
      "market_consensus_status":(consensus or {}).get("schema_version","NOT_SUPPLIED"),
      "probability_fusion":"SHADOW_ONLY_DISABLED_PENDING_CHRONOLOGICAL_OOS_VALIDATION",
      "games":rows,"game_count":len(rows),"market_keys":list(MARKETS),
      "ready_counts":{k:sum(r["markets"][k]["status"]=="DIRECTION_ISSUED" for r in rows) for k in MARKETS},
      "priority_weights":{"jingcai":0.7,"crown":0.3},
      "priority_note":"Workflow and display attention only; never blend market probabilities",
      "primary_market_keys":list(MARKETS[:3]),
      "jingcai_three_ready_games":sum(all(row["markets"][k]["status"]=="DIRECTION_ISSUED" for k in MARKETS[:3]) for row in rows),
      "not_betting_advice":True}

def build_consensus_for_test(joined,companies,top):
    from nba_market_consensus import build
    markets={}
    for kind in ("full_spread","full_total"):
        target_line=6.5 if kind=="full_spread" else 229.5
        markets[kind]={"companies":[
            {"company_id":x["company_id"],"source":x["source"],
             "source_capture_utc":x["source_capture_utc"],
             "current":x["current"]}
            for x in companies if x["current"]["line"]==target_line]}
    top_doc={**top,"games":[{"game_id":"170","markets":markets}]}
    return build(joined,top_doc)


def m_consensus_present(forecast,key):
    return forecast["games"][0]["markets"][key]["market_consensus"]["status"]=="CONSENSUS_AVAILABLE"


def self_test():
    joined={"requested_display_date":"2026-10-31","captured_at_utc":"2026-10-30T14:00:00Z",
      "crown_quote_captured_at_utc":"2026-10-30T14:00:00Z","crown_source_id":"3",
      "nba_cba_games":[{"game_id":"170","nba_game_id":"nba170","league":"NBA",
        "home_team":"独行侠","away_team":"火箭","market_source_id":"3",
        "start_time_beijing":"2026-10-31T08:00:00+08:00",
        "markets":{"full_spread":{"current":{"line":6.5,"first_side_water":0.91,"second_side_water":0.95}},
                   "full_total":{"current":{"line":229.5,"first_side_water":0.92,"second_side_water":0.94}}}}]}
    model={"games":[{"game_id":"170","model_status":"OK","margin_mean_home_minus_away":-6,
                     "total_mean":230,"margin_sigma":12,"total_sigma":18,
                     "model_probability":{"home":0.42,"away":0.58}}]}
    jc={"jc_007_match_numbers":{"games":{"170":{"status":"VERIFIED_JC_NUMBER","label":"周五314"}}},
       "jc_007_public_odds_shadow":{"captured_at_utc":"2026-10-30T14:00:00Z",
         "007_jingcai_reference_user_confirmed":True,
         "games":[{"game_id":"170","markets":{
           "win_lose":{"status":"OBSERVED","data":{"current":{"first_side":2.95,"second_side":1.19}}},
           "handicap":{"status":"OBSERVED","data":{"current":{"line":7.5,"first_side":1.75,"second_side":1.65}}},
           "total":{"status":"OBSERVED","data":{"current":{"line":225.5,"first_side":1.70,"second_side":1.70}}}}}]}}
    # A synchronous five-company quote set should enrich all comparable
    # selections while leaving the actual production probabilities untouched.
    top={"captured_at_utc":"2026-10-30T14:00:00Z","collection_completed_at_utc":"2026-10-30T14:01:00Z","games":[]}
    companies=[{"company_id":cid,"source":"DATED_007_COMPANY_ID",
        "source_capture_utc":"2026-10-30T14:00:00Z",
        "current":{"line":6.5 if kind=="full_spread" else 229.5,
                   "first_side_water":0.91,"second_side_water":0.95}}
        for cid in ("3","1","2","8","9") for kind in ("full_spread","full_total")]
    consensus=build_consensus_for_test(joined,companies,top)
    out=make(joined,model,jc,top,consensus)
    assert out["market_consensus_status"]=="nba-007-market-consensus-v2-same-line-price-shadow"
    assert m_consensus_present(out,"JINGCAI_HANDICAP")
    assert out["games"][0]["markets"]["JINGCAI_WIN"]["market_consensus"]["proxy_type"]=="SPREAD_FAVORITE_NOT_MONEYLINE_ODDS"
    m=out["games"][0]["markets"]
    assert out["ready_counts"]=={k:1 for k in MARKETS}
    assert m["JINGCAI_WIN"]["direction"]=="AWAY_WIN"
    assert m["JINGCAI_HANDICAP"]["direction"]=="HOME_COVER"
    assert m["JINGCAI_HANDICAP"]["signed_home_handicap"]==7.5
    assert m["JINGCAI_TOTAL"]["direction"]=="OVER"
    assert m["CROWN_HANDICAP"]["direction"]=="AWAY_COVER"
    assert m["CROWN_HANDICAP"]["signed_home_handicap"]==-6.5
    assert m["CROWN_TOTAL"]["direction"]=="OVER"
    assert m["CROWN_TOTAL"]["source_id"]=="3"
    assert m["CROWN_TOTAL"]["raw_water_slots"]["first_side"]==0.92
    assert m["CROWN_HANDICAP"]["probability_status"]=="MODEL_NORMAL_UNCALIBRATED_CROWN_ID3"

    # The Crown market is independently missing per game/market; do not
    # replace a missing total with a spread or another bookmaker's quote.
    partial={"requested_display_date":joined["requested_display_date"],
      "captured_at_utc":joined["captured_at_utc"],"crown_quote_captured_at_utc":joined["crown_quote_captured_at_utc"],
      "crown_source_id":"3","nba_cba_games":[{**joined["nba_cba_games"][0],
      "markets":{"full_spread":joined["nba_cba_games"][0]["markets"]["full_spread"],"full_total":{"current":{}}}}]}
    partial_out=make(partial,model,jc,top)["games"][0]["markets"]
    assert partial_out["CROWN_HANDICAP"]["direction"]=="AWAY_COVER"
    assert partial_out["CROWN_TOTAL"]["status"]=="CROWN_ID3_QUOTE_MISSING"
    assert partial_out["CROWN_TOTAL"]["direction"] is None

    # If the canonical capture lacks a live quote, a prior ID3 quote may only
    # be used when its own timestamp is verified pre-tip and is visibly stale.
    no_live={"requested_display_date":joined["requested_display_date"],
      "captured_at_utc":joined["captured_at_utc"],"crown_source_id":"3",
      "nba_cba_games":[{**joined["nba_cba_games"][0],"markets":{}}]}
    archived={"captured_at_utc":"2026-10-30T13:00:00Z","games":[{"game_id":"170","markets":{
      "full_spread":{"companies":[{"company_id":"3","source":"DATED_007_COMPANY_ID_ARCHIVED_PRETIP",
        "observed_capture_utc":"2026-10-30T13:00:00Z","current":{"line":6.5}}]},
      "full_total":{"companies":[{"company_id":"3","source":"DATED_007_COMPANY_ID_ARCHIVED_PRETIP",
        "observed_capture_utc":"2026-10-30T13:00:00Z","current":{"line":229.5}}]}}}]}
    recovered=make(no_live,model,jc,archived)["games"][0]["markets"]
    assert recovered["CROWN_HANDICAP"]["direction"]=="AWAY_COVER"
    assert recovered["CROWN_TOTAL"]["direction"]=="OVER"
    assert recovered["CROWN_TOTAL"]["quote_freshness"]=="ARCHIVED_PRIOR_NOT_LIVE"

    # A non-ID3 source must never be promoted as Crown.
    wrong_source={**joined,"crown_source_id":"9"}
    wrong=make(wrong_source,model,jc,top)["games"][0]["markets"]
    assert wrong["CROWN_HANDICAP"]["direction"] is None
    assert wrong["CROWN_TOTAL"]["direction"] is None

    # Jingcai numbering is display metadata only; it must not block Crown or
    # the three 007 price/line observations when a label lookup is unavailable.
    jc["jc_007_match_numbers"]["games"]["170"]={"status":"UNVERIFIED","label":None}
    independent=make(joined,model,jc,top)["games"][0]
    assert independent["jingcai_number"] is None
    assert independent["markets"]["JINGCAI_HANDICAP"]["direction"]=="HOME_COVER"
    assert independent["markets"]["CROWN_HANDICAP"]["direction"]=="AWAY_COVER"
    assert out["priority_weights"]=={"jingcai":0.7,"crown":0.3}
    assert out["jingcai_three_ready_games"]==1

    # A post-tip ID3 snapshot is not a valid pre-game quote.
    late={**joined,"crown_quote_captured_at_utc":"2026-10-31T02:00:00Z"}
    late_out=make(late,model,jc,top)["games"][0]["markets"]
    assert late_out["CROWN_HANDICAP"]["direction"] is None
    assert late_out["CROWN_TOTAL"]["direction"] is None

    # A post-tip Jingcai capture is not accepted.
    jc["jc_007_public_odds_shadow"]["captured_at_utc"]="2026-10-31T02:00:00Z"
    late_jc=make(joined,model,jc,top)["games"][0]["markets"]
    assert all(late_jc[k]["direction"] is None for k in MARKETS[:3])
    print("NBA_FIVE_MARKETS_CANONICAL_007_SOURCE_SELFTEST_PASS")

if __name__=="__main__":
    a=argparse.ArgumentParser()
    a.add_argument("--joined");a.add_argument("--model");a.add_argument("--jingcai");a.add_argument("--top10");a.add_argument("--consensus");a.add_argument("--out");a.add_argument("--self-test",action="store_true")
    v=a.parse_args()
    if v.self_test:self_test()
    else:
        if not all((v.joined,v.model,v.jingcai,v.top10,v.out)):raise SystemExit("REQUIRED_INPUT_MISSING")
        def load(p):return json.loads(Path(p).read_text(encoding="utf-8"))
        o=make(load(v.joined),load(v.model),load(v.jingcai),load(v.top10),
               load(v.consensus) if v.consensus else None)
        Path(v.out).write_text(json.dumps(o,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        print("NBA_FIVE_MARKETS_PRODUCED",json.dumps({"games":o["game_count"],"counts":o["ready_counts"]},ensure_ascii=False))
