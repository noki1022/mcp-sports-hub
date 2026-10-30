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

def make(joined,model,jc,top10):
    date=joined.get("requested_display_date")
    board=idx([g for g in joined.get("nba_cba_games",[]) if g.get("league")=="NBA"])
    preds=idx(model.get("games",[]))
    identity=(jc.get("jc_007_match_numbers") or {}).get("games") or {}
    feed=(jc.get("jc_007_public_odds_shadow") or {})
    prices=idx(feed.get("games",[]))
    institution=idx(top10.get("games",[]))
    capture=when(feed.get("captured_at_utc"))
    institutional_capture=when(top10.get("captured_at_utc"))
    rows=[]
    for gid,g in board.items():
        tip=when(g.get("start_time_beijing"))
        label=(identity.get(gid) or {}).get("label")
        verified=((identity.get(gid) or {}).get("status")=="VERIFIED_JC_NUMBER"
                  and re.fullmatch(r"周[一二三四五六日天]\d{3}",str(label or "")) is not None)
        p=preds.get(gid,{})
        margin=n(p.get("margin_mean_home_minus_away")) if p.get("model_status") in ("OK","PARTIAL") else None
        total=n(p.get("total_mean")) if p.get("model_status") in ("OK","PARTIAL") else None
        jc_valid=bool(verified and capture and tip and capture<tip)
        crow_valid=bool(verified and institutional_capture and tip and institutional_capture<tip)
        pools=(prices.get(gid) or {}).get("markets") or {}
        def jc_market(key,market):
            item=pools.get(key) or {}
            state=item.get("status","NO_QUOTE_IN_007_FEED")
            if state!="OBSERVED":
                return selection(market,None,None,status=state,source="007_JINGCAI")
            cur=(item.get("data") or {}).get("current") or {}
            line=n(cur.get("line"))
            if not jc_valid:return selection(market,None,line,status="JC_PRICE_OR_ID_UNVERIFIED",source="007_JINGCAI")
            if key=="win_lose":
                return selection(market,margin,None,observed_at=feed.get("captured_at_utc"),source="007_JINGCAI")
            if line is None:return selection(market,None,None,status="INVALID_JC_LINE",source="007_JINGCAI")
            gap=(margin+line) if key=="handicap" and margin is not None else (
                 total-line if key=="total" and total is not None else None)
            return selection(market,gap,line,observed_at=feed.get("captured_at_utc"),source="007_JINGCAI")
        selected={"JINGCAI_WIN":jc_market("win_lose","JINGCAI_WIN"),
                  "JINGCAI_HANDICAP":jc_market("handicap","JINGCAI_HANDICAP"),
                  "JINGCAI_TOTAL":jc_market("total","JINGCAI_TOTAL")}
        im=(institution.get(gid) or {}).get("markets") or {}
        for kind,market in (("full_spread","CROWN_HANDICAP"),("full_total","CROWN_TOTAL")):
            company=(im.get(kind) or {}).get("companies") or []
            live=[c for c in company if str(c.get("company_id"))=="3"
                  and c.get("source")=="DATED_007_COMPANY_ID"]
            archived=[c for c in company if str(c.get("company_id"))=="3"
                      and c.get("source")=="DATED_007_COMPANY_ID_ARCHIVED_PRETIP"]
            matches=live if live else archived
            archived_fallback=not live and bool(archived)
            if len(matches)!=1 or not crow_valid:
                selected[market]=selection(market,None,None,source="007_CROWN_ID3",
                    status="CROWN_QUOTE_NOT_VERIFIED",source_id="3")
                continue
            quote=(matches[0].get("current") or {})
            line=n(quote.get("line"))
            if line is None:
                selected[market]=selection(market,None,None,source="007_CROWN_ID3",
                    status="INVALID_CROWN_LINE",source_id="3")
                continue
            # Crow* raw positive line denotes home gives, not the JC home receiver.
            gap=((margin-line) if kind=="full_spread" and margin is not None else
                 (total-line) if kind=="full_total" and total is not None else None)
            quote_time=(matches[0].get("observed_capture_utc") if archived_fallback
                        else top10.get("captured_at_utc"))
            actual_time=when(quote_time)
            if actual_time is None or tip is None or actual_time>=tip:
                selected[market]=selection(market,None,line,status="CROWN_ARCHIVE_NOT_PRETIP",
                    source="007_CROWN_ID3",source_id="3")
                continue
            selected[market]=selection(market,gap,line,
                source="007_CROWN_ID3_ARCHIVED_PRETIP" if archived_fallback else "007_CROWN_ID3",
                source_id="3",observed_at=quote_time)
            selected[market]["quote_freshness"]=("ARCHIVED_PRIOR_NOT_LIVE" if archived_fallback else "CURRENT_CAPTURE")
        assert set(selected)==set(MARKETS)
        rows.append({"game_id":gid,"nba_game_id":g.get("nba_game_id"),
          "jingcai_number":label if verified else None,
          "home_team":g.get("home_team"),"away_team":g.get("away_team"),
          "tipoff_beijing":g.get("start_time_beijing"),
          "model_margin_home_minus_away":margin,"model_total":total,
          "markets":selected})
    return {"schema_version":"nba-five-markets-v1",
      "target_date":date,"board_capture_utc":joined.get("captured_at_utc"),
      "market_settlement_lock":"CAPTURED_PRETIP_ONLY",
      "crown_company_id":"3","crown_source":"007 source ID 3 (Crow* label crosscheck required)",
      "games":rows,"game_count":len(rows),"market_keys":list(MARKETS),
      "ready_counts":{k:sum(r["markets"][k]["status"]=="DIRECTION_ISSUED" for r in rows) for k in MARKETS},
      "not_betting_advice":True}

def self_test():
    joined={"requested_display_date":"2026-10-31","captured_at_utc":"2026-10-30T14:00:00Z",
      "nba_cba_games":[{"game_id":"170","nba_game_id":"nba170","league":"NBA",
        "home_team":"独行侠","away_team":"火箭","start_time_beijing":"2026-10-31T08:00:00+08:00"}]}
    model={"games":[{"game_id":"170","model_status":"OK","margin_mean_home_minus_away":-6,
                     "total_mean":230}]}
    jc={"jc_007_match_numbers":{"games":{"170":{"status":"VERIFIED_JC_NUMBER","label":"周五314"}}},
       "jc_007_public_odds_shadow":{"captured_at_utc":"2026-10-30T14:00:00Z",
         "games":[{"game_id":"170","markets":{
           "win_lose":{"status":"OBSERVED","data":{"current":{"first_side":2.95,"second_side":1.19}}},
           "handicap":{"status":"OBSERVED","data":{"current":{"line":7.5,"first_side":1.75,"second_side":1.65}}},
           "total":{"status":"OBSERVED","data":{"current":{"line":225.5,"first_side":1.70,"second_side":1.70}}}}}]}}
    top = {
      "captured_at_utc": "2026-10-30T14:00:00Z",
      "games": [{
        "game_id": "170",
        "markets": {
          "full_spread": {"companies": [{
            "company_id": "3", "source": "DATED_007_COMPANY_ID",
            "current": {"line": 6.5}
          }]},
          "full_total": {"companies": [{
            "company_id": "3", "source": "DATED_007_COMPANY_ID",
            "current": {"line": 229.5}
          }]}
        }
      }]
    }
    out=make(joined,model,jc,top)
    m=out["games"][0]["markets"]
    assert out["ready_counts"]=={k:1 for k in MARKETS}
    assert m["JINGCAI_WIN"]["direction"]=="AWAY_WIN"
    assert m["JINGCAI_HANDICAP"]["direction"]=="HOME_COVER"
    assert m["JINGCAI_HANDICAP"]["signed_home_handicap"]==7.5
    assert m["CROWN_HANDICAP"]["direction"]=="AWAY_COVER"
    assert m["CROWN_HANDICAP"]["signed_home_handicap"]==-6.5
    assert m["JINGCAI_TOTAL"]["direction"]=="OVER"
    assert m["CROWN_TOTAL"]["direction"]=="OVER"
    jc["jc_007_public_odds_shadow"]["games"][0]["markets"]["win_lose"]={"status":"NOT_ON_SALE_USER_CONFIRMED"}
    missing=make(joined,model,jc,top)
    assert missing["games"][0]["markets"]["JINGCAI_WIN"]["status"]=="NOT_ON_SALE_USER_CONFIRMED"
    assert missing["ready_counts"]["JINGCAI_WIN"]==0
    top["games"][0]["markets"]["full_spread"]["companies"][0]["company_id"]="9"
    assert make(joined,model,jc,top)["games"][0]["markets"]["CROWN_HANDICAP"]["direction"] is None
    top["games"][0]["markets"]["full_spread"]["companies"]=[{
        "company_id":"3","source":"DATED_007_COMPANY_ID_ARCHIVED_PRETIP",
        "observed_capture_utc":"2026-10-30T13:00:00Z","current":{"line":6.5}}]
    top["games"][0]["markets"]["full_total"]["companies"]=[{
        "company_id":"3","source":"DATED_007_COMPANY_ID_ARCHIVED_PRETIP",
        "observed_capture_utc":"2026-10-30T13:00:00Z","current":{"line":229.5}}]
    recovered=make(joined,model,jc,top)["games"][0]["markets"]
    assert recovered["CROWN_HANDICAP"]["direction"]=="AWAY_COVER"
    assert recovered["CROWN_TOTAL"]["direction"]=="OVER"
    assert recovered["CROWN_TOTAL"]["quote_freshness"]=="ARCHIVED_PRIOR_NOT_LIVE"
    assert recovered["CROWN_TOTAL"]["source_id"]=="3"
    print("NBA_FIVE_MARKETS_DIRECTION_AND_SOURCE_SELFTEST_PASS")

if __name__=="__main__":
    a=argparse.ArgumentParser()
    a.add_argument("--joined");a.add_argument("--model");a.add_argument("--jingcai");a.add_argument("--top10");a.add_argument("--out");a.add_argument("--self-test",action="store_true")
    v=a.parse_args()
    if v.self_test:self_test()
    else:
        if not all((v.joined,v.model,v.jingcai,v.top10,v.out)):raise SystemExit("REQUIRED_INPUT_MISSING")
        def load(p):return json.loads(Path(p).read_text(encoding="utf-8"))
        o=make(load(v.joined),load(v.model),load(v.jingcai),load(v.top10))
        Path(v.out).write_text(json.dumps(o,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        print("NBA_FIVE_MARKETS_PRODUCED",json.dumps({"games":o["game_count"],"counts":o["ready_counts"]},ensure_ascii=False))
