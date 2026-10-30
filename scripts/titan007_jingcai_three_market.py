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
    # Explicit dependency injection lets tests prove all three types are
    # checked even when access is blocked; no fake odds can be produced.
    if get is None:get=urllib.request.urlopen
    check_time=datetime.now(timezone.utc).isoformat()
    policy={"state":"UNVERIFIED","reason":"ROBOTS_CHECK_NOT_ATTEMPTED"}
    try:
        req=urllib.request.Request(BASE+"/robots.txt",headers={"User-Agent":UA})
        with get(req,timeout=8) as resp:
            robots=resp.read(60000).decode("utf-8","replace")
        parser=urllib.robotparser.RobotFileParser()
        parser.parse(robots.splitlines())
        policy={"state":"FETCHED","robots_checked":True}
    except urllib.error.HTTPError as exc:
        if exc.code in (404,410):
            parser=urllib.robotparser.RobotFileParser();parser.parse([])
            policy={"state":"NO_ROBOTS_FILE","robots_checked":True}
        else:
            parser=None;policy={"state":"NOT_VERIFIED","reason":"ROBOTS_HTTP_"+str(exc.code)}
    except (OSError,ValueError,RuntimeError) as exc:
        parser=None;policy={"state":"NOT_VERIFIED","reason":type(exc).__name__}
    sources={}
    for key,tid in SOURCE_MAP.items():
        uri=f"{BASE}{PAGE}?TypeID={tid}&OddsType=2"
        record={"type_id":tid,"url":uri,"status":"UNAVAILABLE","live_pricing_rows":0}
        if parser is None:record["reason"]="ROBOTS_POLICY_NOT_VERIFIED"
        elif not parser.can_fetch(UA,uri):
            record["status"]="ACCESS_DISALLOWED"
            record["reason"]="PUBLISHED_ROBOTS_DISALLOW"
        else:
            # The previous read-only audit only proved page accessibility, not
            # a trusted match-by-match odds schema. Do not treat unparsed HTML
            # as correct current fixed bonuses.
            record["status"]="PARSER_NOT_VERIFIED"
            record["reason"]="SOURCE_NOT_YET_SCHEMA_VERIFIED"
        sources[key]=record
    games=[]
    for g in board.get("nba_cba_games",[]):
        if g.get("league")!="NBA":continue
        games.append({"game_id":str(g["game_id"]),"nba_game_id":str(g.get("nba_game_id")),
           "home_team":g.get("home_team"),"away_team":g.get("away_team"),
           "markets":{m:{"status":"NO_VERIFIED_JINGCAI_ODDS",
                         "line":None,"home_odds":None,"away_odds":None,
                         "reason":sources[m]["reason"]} for m in SOURCE_MAP}})
    return {"schema_version":"007-jingcai-three-market-source-audit-v1",
       "target_date":board.get("requested_display_date"),"captured_at_utc":board.get("captured_at_utc"),
       "inspected_at_utc":check_time,"pricing_source":"007_THIRD_PARTY_NOT_OFFICIAL",
       "robots_policy":policy,"source_status":sources,"games":games,
       "game_count":len(games),"verified_games_with_all_three":0,
       "model_fusion_enabled":False,"jingcai_return_calculation_enabled":False,
       "status":"JINGCAI_PRICES_UNAVAILABLE_DO_NOT_USE_COMMERCIAL_ODDS_AS_PROXY"}

def test():
    class Response:
        def __init__(self,txt):self.txt=txt
        def __enter__(self):return self
        def __exit__(self,*a):return False
        def read(self,*a):return self.txt.encode()
    def fake(req,timeout=8):
        assert req.full_url.endswith("/robots.txt")
        return Response("User-agent: *\nDisallow: /\n")
    board={"requested_display_date":"2026-10-31","captured_at_utc":"2026-10-30T10:00:00+00:00",
        "nba_cba_games":[{"league":"NBA","game_id":"728165","nba_game_id":"401909277",
                          "home_team":"奇才","away_team":"黄蜂"}]}
    x=inspect_sources(board,get=fake)
    assert set(x["source_status"])==set(SOURCE_MAP)
    assert all(v["status"]=="ACCESS_DISALLOWED" for v in x["source_status"].values())
    assert x["verified_games_with_all_three"]==0
    assert all(v["home_odds"] is None for v in x["games"][0]["markets"].values())
    assert not x["model_fusion_enabled"]
    print("JINGCAI_ALL_THREE_MARKETS_FAIL_CLOSED_TEST_PASS")

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
        Path(a.out).write_text(json.dumps(x,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        print("JINGCAI_THREE_MARKET_AUDIT",x["game_count"],x["verified_games_with_all_three"],
             {k:v["status"] for k,v in x["source_status"].items()})
