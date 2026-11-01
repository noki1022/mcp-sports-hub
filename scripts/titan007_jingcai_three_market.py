#!/usr/bin/env python3
"""Audit three user-supplied 007 JingCaiBasket pricing pages on EVERY NBA snapshot.

Never bypass robots/anti-bot restrictions, assume page HTML is authoritative
lottery fixed-odds data, or fabricate price/line/team matching. Nonzero source
coverage requires explicit verified independently usable parser in future.
"""
import argparse,json,urllib.request,urllib.error,urllib.robotparser
from pathlib import Path
from datetime import datetime,timezone

BASE="https://cp.titan007.com"
PAGE="/buy/JingCaiBasket.aspx"
SOURCE_MAP={"WIN_LOSE":"111","HANDICAP_WIN_LOSE":"112","TOTAL":"114"}
UA="NBA-Jingcai-Public-Research/1.0"

def inspect_sources(board, *, get=None):
    # The CP HTML pages are not the pricing source. The independently parsed
    # 007 public XML feed below is canonical; do not request a disallowed
    # alternate page and then report the real XML feed as unavailable.
    check_time=datetime.now(timezone.utc).isoformat()
    sources={}
    for key,tid in SOURCE_MAP.items():
        sources[key]={
            "type_id":tid,
            "url":"https://jc.titan007.com/xml/odds_jc_lq.txt",
            "status":"AWAITING_CANONICAL_XML_AUDIT",
            "live_pricing_rows":0,
            "reason":"CANONICAL_007_XML_FEED_IS_CHECKED_BELOW"}
    games=[]
    for g in board.get("nba_cba_games",[]):
        if g.get("league")!="NBA":continue
        games.append({"game_id":str(g["game_id"]),"nba_game_id":str(g.get("nba_game_id")),
           "home_team":g.get("home_team"),"away_team":g.get("away_team"),
           "markets":{m:{"status":"AWAITING_CANONICAL_XML_AUDIT",
                         "line":None,"home_odds":None,"away_odds":None,
                         "reason":"CANONICAL_007_XML_FEED_IS_CHECKED_BELOW"} for m in SOURCE_MAP}})
    return {"schema_version":"007-jingcai-three-market-source-audit-v1",
       "target_date":board.get("requested_display_date"),"captured_at_utc":board.get("captured_at_utc"),
       "inspected_at_utc":check_time,"pricing_source":"007_USER_CONFIRMED_JINGCAI_REFERENCE",
       "source_status":sources,"games":games,
       "game_count":len(games),"verified_games_with_all_three":0,
       "model_fusion_enabled":False,"jingcai_return_calculation_enabled":False,
       "direction_slot_order_verified":False,
       "status":"AWAITING_CANONICAL_007_XML_AUDIT"}

def test():
    calls=[]
    def fake(req,timeout=8):
        calls.append(req.full_url)
        raise AssertionError("ALTERNATE_CP_PAGE_MUST_NOT_BE_REQUESTED")
    board={"requested_display_date":"2026-10-31","captured_at_utc":"2026-10-30T10:00:00+00:00",
        "nba_cba_games":[{"league":"NBA","game_id":"728165","nba_game_id":"401909277",
                          "home_team":"奇才","away_team":"黄蜂"}]}
    x=inspect_sources(board,get=fake)
    assert set(x["source_status"])==set(SOURCE_MAP)
    assert all(v["status"]=="AWAITING_CANONICAL_XML_AUDIT" for v in x["source_status"].values())
    assert x["verified_games_with_all_three"]==0
    assert all(v["status"]=="AWAITING_CANONICAL_XML_AUDIT"
               for v in x["games"][0]["markets"].values())
    assert not x["model_fusion_enabled"] and not calls
    print("JINGCAI_CANONICAL_XML_AUDIT_STATE_TEST_PASS")

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--joined");p.add_argument("--out");p.add_argument("--self-test",action="store_true")
    a=p.parse_args()
    if a.self_test:test()
    else:
        if not a.joined or not a.out:raise SystemExit("MISSING_ARGS")
        board=json.loads(Path(a.joined).read_text(encoding="utf-8"))
        x=inspect_sources(board)
        from marzdata_jingcai import enrich
        x=enrich(board,x)
        # Independent 007-only public JC price feed. Shadow data only:
        # do not promote unverified side orientation/third-party prices into
        # official lottery payouts, wagering EV, or existing recommendation gates.
        try:
            from parse_007_jc_three_market import parse as parse_jc,PATH as jc_path
            from probe_007_jc_scripts import ORIGIN as jc_origin, UA as jc_ua, get_bytes as jc_get, robots_policy as jc_robots
            rp,robots_status=jc_robots()
            if rp is False or (rp is not None and not rp.can_fetch(jc_ua,jc_origin+jc_path)):
                raise RuntimeError("JC_SOURCE_NOT_PERMITTED_"+robots_status)
            shadow=parse_jc(jc_get(jc_origin+jc_path,300000),board)
            x["jc_007_public_odds_shadow"]={"status":"AVAILABLE_007_USER_CONFIRMED_REFERENCE_DIRECTION_SLOTS_PENDING",
                "source":shadow["url"],"captured_at_utc":shadow["captured_at_utc"],
                "nba_coverage":shadow["nba_coverage"],
                "all_three_market_games":shadow["all_three_market_games"],
                "games":shadow["matches"],
                "official_fixed_bonus_verified":False,
                "007_jingcai_reference_user_confirmed":shadow.get("007_jingcai_reference_user_confirmed",False),
                "direction_slot_order_verified":False,
                "eligible_for_model_fusion":False}
            coverage=shadow["nba_coverage"]
            mapping={"WIN_LOSE":"win_lose","HANDICAP_WIN_LOSE":"handicap","TOTAL":"total"}
            for market,source_key in mapping.items():
                x["source_status"][market].update({
                    "status":"AVAILABLE_007_XML_REFERENCE",
                    "reason":"USER_CONFIRMED_007_JINGCAI_REFERENCE",
                    "live_pricing_rows":shadow.get("source_record_counts",{}).get(source_key,0),
                    "matched_games":coverage.get(source_key,0)})
            x["verified_games_with_all_three"]=shadow["all_three_market_games"]
            x["pricing_source"]="007_USER_CONFIRMED_JINGCAI_REFERENCE"
            x["direction_slot_order_verified"]=False
            x["status"]="AVAILABLE_007_XML_REFERENCE_DIRECTION_SLOTS_PENDING"
            print("JC_007_PUBLIC_THREE_MARKET_SHADOW",shadow["nba_coverage"],shadow["all_three_market_games"])
        except (OSError,ValueError,RuntimeError,ImportError,KeyError) as exc:
            x["jc_007_public_odds_shadow"]={"status":"UNAVAILABLE","error_type":type(exc).__name__,
                "official_fixed_bonus_verified":False,"eligible_for_model_fusion":False,"games":[]}
            print("JC_007_PUBLIC_THREE_MARKET_SHADOW_UNAVAILABLE",type(exc).__name__)
        # All user-facing match numbers come from 007 JC *fixture* labels.
        # A verified 007 ID, home/away identity and Beijing tipoff is mandatory.
        # Each failure has an explicit reason: never generate 309 + report index.
        try:
            from verify_007_jc_push_numbering import live as read_jc_labels
            x["jc_007_match_numbers"]=read_jc_labels(board)
            print("JC_007_LOTTERY_MATCH_NUMBERS",x["jc_007_match_numbers"]["verified"],
                  x["jc_007_match_numbers"]["total_games"])
        except (OSError,ValueError,RuntimeError,ImportError,KeyError) as exc:
            x["jc_007_match_numbers"]={"status":"UNAVAILABLE","verified":0,
                "total_games":len([g for g in board.get("nba_cba_games",[]) if g.get("league")=="NBA"]),
                "error_type":type(exc).__name__,"games":{}}
            print("JC_007_LOTTERY_MATCH_NUMBERS_UNAVAILABLE",type(exc).__name__)
        Path(a.out).write_text(json.dumps(x,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        print("JINGCAI_THREE_MARKET_AUDIT",x["game_count"],x["verified_games_with_all_three"],
             {k:v["status"] for k,v in x["source_status"].items()})
