#!/usr/bin/env python3
"""Offline crosswalk: screenshot-displayed Jingcai totals vs verified 007 NBA board.

Never use inferred shared teams to assert a Jingcai issue number, live payout,
contemporaneous bookmaker line, verified team IDs, model EV, or official odds.
"""
from __future__ import annotations
import argparse,json,re
from pathlib import Path
from collections import Counter

def norm(text):
    return re.sub(r"[\s\[\]（）()·]+","",str(text).lower().strip())

def alias_match(full,short):
    a,b=norm(full),norm(short)
    return bool(a and b and (a==b or (len(b)>=2 and a.endswith(b))))

def crosswalk(board,screen):
    if screen.get("source")!="USER_SUPPLIED_007_SCREENSHOT" or screen.get("source_is_official") is not False:
        raise ValueError("SCREENSHOT_SOURCE_NOT_VERIFIED")
    day=board.get("requested_display_date")
    if not day or day not in screen.get("display_window",""):
        raise ValueError("DISPLAY_WINDOW_DAY_MISMATCH")
    games=board.get("nba_cba_games",[])
    rows=screen.get("rows",[])
    if not games or not rows:raise ValueError("EMPTY_REFERENCE")
    if len({str(g["game_id"]) for g in games})!=len(games):
        raise ValueError("DUPLICATE_BOOKMAKER_GAME")
    if len({str(r["match_no"]) for r in rows})!=len(rows):
        raise ValueError("DUPLICATE_SCREENSHOT_MATCH_NUMBER")
    used=set()
    entries=[]
    for row in rows:
        candidates=[g for g in games if g.get("league")=="NBA"
            and alias_match(g.get("home_team",""),row.get("home",""))
            and alias_match(g.get("away_team",""),row.get("away",""))]
        if len(candidates)!=1:
            entries.append({"match_no":row["match_no"],"state":"UNMATCHED_OR_AMBIGUOUS_TEAMS",
                            "candidates":len(candidates)})
            continue
        g=candidates[0]
        if g["game_id"] in used:raise ValueError("SAME_REFERENCE_GAME_USED_TWICE")
        used.add(g["game_id"])
        price=row.get("total",{})
        if price.get("source")!="007_JINGCAI_DISPLAY" or price.get("selection_order")!="LABELED":
            raise ValueError("TOTAL_QUOTE_UNVERIFIED")
        line=price.get("line")
        over=price.get("over")
        under=price.get("under")
        if not all(isinstance(x,(int,float)) and not isinstance(x,bool) for x in (line,over,under)):
            raise ValueError("INCOMPLETE_QUOTE")
        if not (80<=line<=400 and 1<over<30 and 1<under<30):
            raise ValueError("INVALID_PRICE_OR_LINE")
        imp_over,imp_under=1/over,1/under
        norm_over=imp_over/(imp_over+imp_under)
        other_line=g["markets"]["full_total"]["current"]["line"]
        entries.append({"match_no":row["match_no"],"game_id":g["game_id"],
            "nba_game_id":g.get("nba_game_id"),
            "home_team":g["home_team"],"away_team":g["away_team"],
            "beijing_tip":g.get("start_time_beijing"),
            "state":"TEAM_AND_DATE_WINDOW_CROSSWALK_ONLY",
            "jingcai_match_number_verified_in_public_feed":False,
            "screenshot_total":{"line":line,"over":over,"under":under,
                "no_vig_over_probability":round(norm_over,6),
                "no_vig_under_probability":round(1-norm_over,6),
                "overround":round(imp_over+imp_under-1,6)},
            "007_institution_total":{"line":other_line,"orientation":"UNVERIFIED"},
            "screenshot_minus_institution_line":round(line-other_line,2),
            "same_capture_time_verified":False,
            "screenshot_timestamp":"NOT_VISIBLE",
            "evidence":"MANUAL_SCREENSHOT_PLUS_SEPARATE_007_BOARD"})
    return {"schema_version":"007-jingcai-screenshot-crosswalk-v1",
        "beijing_date":day,"matched":sum("game_id" in r for r in entries),
        "unmatched":sum("game_id" not in r for r in entries),
        "jinacai_fixed_pricing_live_verified":False,
        "official_lottery_odds_verified":False,
        "model_ev_enabled":False,"live_payout_enabled":False,
        "caution":"Different capture times; screenshot is third-party Jingcai display, not official odds or direct automatic access.",
        "rows":entries}

def self_test():
    board={"requested_display_date":"2026-10-31","nba_cba_games":[
      {"game_id":"728165","nba_game_id":"401909277","league":"NBA",
       "home_team":"华盛顿奇才","away_team":"夏洛特黄蜂",
       "markets":{"full_total":{"current":{"line":220.5}}}}]}
    screen={"source":"USER_SUPPLIED_007_SCREENSHOT","source_is_official":False,
      "display_window":"2026-10-30 to 2026-10-31","rows":[{"match_no":"309",
      "home":"奇才","away":"黄蜂","total":{"source":"007_JINGCAI_DISPLAY",
      "selection_order":"LABELED","line":221.5,"over":1.62,"under":1.78}}]}
    r=crosswalk(board,screen)
    assert r["matched"]==1 and r["rows"][0]["screenshot_minus_institution_line"]==1.0
    assert abs(sum(r["rows"][0]["screenshot_total"][x] for x in ("no_vig_over_probability","no_vig_under_probability"))-1)<1e-8
    assert not r["model_ev_enabled"] and not r["live_payout_enabled"]
    swapped=json.loads(json.dumps(screen))
    swapped["rows"][0]["home"],swapped["rows"][0]["away"]="黄蜂","奇才"
    assert crosswalk(board,swapped)["unmatched"]==1
    print("JINGCAI_SCREENSHOT_TOTAL_CROSSWALK_SELF_TEST_PASS")

if __name__=="__main__":
    a=argparse.ArgumentParser()
    a.add_argument("--board");a.add_argument("--screen");a.add_argument("--output")
    a.add_argument("--self-test",action="store_true")
    args=a.parse_args()
    if args.self_test:self_test()
    else:
        if not all((args.board,args.screen,args.output)):raise SystemExit("REQUIRED_FLAGS")
        result=crosswalk(json.loads(Path(args.board).read_text(encoding="utf-8")),
             json.loads(Path(args.screen).read_text(encoding="utf-8")))
        Path(args.output).write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        print("JC_SCREENSHOT_TOTAL_CROSSWALK",json.dumps({"matched":result["matched"],
             "unmatched":result["unmatched"],"odds_live_verified":False,
             "margins":{r.get("game_id",r["match_no"]):r.get("screenshot_minus_institution_line")
                        for r in result["rows"]}},ensure_ascii=False))
