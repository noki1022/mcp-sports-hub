#!/usr/bin/env python3
"""Parse directly verified 007 JC NBA lottery-odds text, without guessing direction.

Source: /xml/odds_jc_lq.txt, discovered in 007 common.js:
  .split('$') => win/loss, handicap win/loss, total.
  .split('!') => records, .split('^') => fields.
  _glJC.jcOddsLq sets first pair+line (_f) then current pair+line.
This is a third-party advertised lottery-odds feed, NOT official lottery data.
"""
from __future__ import annotations
import argparse,json,math,re
from pathlib import Path
from datetime import datetime,timezone
from probe_007_jc_scripts import ORIGIN,UA,get_bytes,robots_policy

PATH="/xml/odds_jc_lq.txt"
MARKETS=("win_lose","handicap","total")
MARKET_ID={"win_lose":"111","handicap":"112","total":"114"}
SALE_NOTE_PATH=Path("config/007_jingcai_source_and_sale_notes.json")

def source_policy_notes(board,notes=None):
    if notes is None:
        notes=json.loads(SALE_NOTE_PATH.read_text(encoding="utf-8")) if SALE_NOTE_PATH.is_file() else {}
    if notes and notes.get("source_policy")!="USE_007_JC_AS_LOTTERY_PRICING_REFERENCE":
        raise ValueError("INVALID_USER_SOURCE_POLICY")
    cases={}
    for note in notes.get("market_sale_status_notes",[]):
        if note.get("date_beijing")!=board.get("requested_display_date"):continue
        if note.get("status")!="NOT_ON_SALE_USER_CONFIRMED":continue
        key=(str(note["game_id"]),note["market"])
        if key in cases:raise ValueError("DUPLICATE_USER_SALE_NOTE")
        cases[key]=note
    return notes,cases

def number(txt):
    if txt=="":return None
    try:
        x=float(txt)
        if not math.isfinite(x):return None
        return x
    except (TypeError,ValueError):return None

def parse(raw, board, source_notes=None):
    policy, sale_notes=source_policy_notes(board,source_notes)
    try:source=raw.decode("utf-8-sig")
    except UnicodeDecodeError:source=raw.decode("gb18030")
    parts=source.split("$")
    if len(parts)!=3:raise ValueError("EXPECTED_THREE_ODDS_MARKET_SECTIONS")
    tables={}
    for market,part in zip(MARKETS,parts):
        rows={}
        for entry in part.split("!"):
            if not entry.strip():continue
            a=entry.split("^")
            if len(a)!=7 or not re.fullmatch(r"\d{4,12}",a[0]):
                raise ValueError("INVALID_ODDS_ROW_FORMAT_"+market)
            gid=a[0]
            if gid in rows:raise ValueError("DUPLICATE_007_GAME_ID_"+gid)
            vals=list(map(number,a[1:]))
            if any(x is None for x in vals):
                raise ValueError("MISSING_ODDS_VALUES_"+market+"_"+gid)
            first_a,first_b,first_line,last_a,last_b,last_line=vals
            if not all(1 < x < 30 for x in (first_a,first_b,last_a,last_b)):
                raise ValueError("ODDS_OUT_OF_RANGE_"+market+"_"+gid)
            if market=="win_lose":
                if first_line != 0 or last_line != 0:raise ValueError("UNEXPECTED_WIN_LINE")
                opening={"first_side":first_a,"second_side":first_b}
                current={"first_side":last_a,"second_side":last_b}
            else:
                if market=="total" and not (80<=first_line<=400 and 80<=last_line<=400):
                    raise ValueError("INVALID_TOTAL_LINE")
                if market=="handicap" and not (-80<=first_line<=80 and -80<=last_line<=80):
                    raise ValueError("INVALID_SPREAD_LINE")
                opening={"line":first_line,"first_side":first_a,"second_side":first_b}
                current={"line":last_line,"first_side":last_a,"second_side":last_b}
            rows[gid]={"opening":opening,"current":current,"line_or_odds_changed":opening!=current}
        tables[market]=rows
    result={"captured_at_utc":datetime.now(timezone.utc).isoformat(),
            "origin":"007_THIRD_PARTY_JC_PUBLIC_XML","url":ORIGIN+PATH,
            "date_beijing":board.get("requested_display_date"),
            "market_ids":MARKET_ID,
            "source_record_counts":{k:len(v) for k,v in tables.items()},
            "official_fixed_bonus_verified":False,
            "007_jingcai_reference_user_confirmed":bool(policy),
            "source_reference_policy":policy.get("source_policy","UNVERIFIED"),
            "first_second_side_orientation":"UNVERIFIED",
            "can_use_for_production_betting":False,
            "matches":[]}
    for g in board.get("nba_cba_games",[]):
        if g.get("league")!="NBA":continue
        gid=str(g["game_id"])
        result["matches"].append({"game_id":gid,"nba_game_id":g.get("nba_game_id"),
          "home_team":g.get("home_team"),"away_team":g.get("away_team"),
          "tipoff_beijing":g.get("start_time_beijing"),
          "markets":{m:({"status":"OBSERVED","data":tables[m][gid]} if gid in tables[m]
                        else ({"status":"NOT_ON_SALE_USER_CONFIRMED","evidence":"EXPLICIT_USER_CONFIRMATION"}
                              if (gid,m) in sale_notes else {"status":"NO_QUOTE_IN_007_FEED"})) for m in MARKETS}})
    result["nba_coverage"]={m:sum(x["markets"][m]["status"]=="OBSERVED" for x in result["matches"]) for m in MARKETS}
    result["nba_games"]=len(result["matches"])
    result["all_three_market_games"]=sum(all(x["markets"][m]["status"]=="OBSERVED" for m in MARKETS) for x in result["matches"])
    return result

def self_test():
    raw=(b"728165^1.5^2.5^0^1.6^2.4^0$"
         b"728165^1.7^1.7^-1.5^1.65^1.75^-3.5$"
         b"728165^1.7^1.7^222.5^1.6^1.8^223.5")
    board={"requested_display_date":"2026-10-31","nba_cba_games":[{"game_id":"728165","nba_game_id":"401909277","league":"NBA",
      "home_team":"华盛顿奇才","away_team":"夏洛特黄蜂"}]}
    x=parse(raw,board)
    assert x["all_three_market_games"]==1
    assert x["matches"][0]["markets"]["handicap"]["data"]["current"]["line"]==-3.5
    assert x["matches"][0]["markets"]["total"]["data"]["opening"]["line"]==222.5
    assert x["matches"][0]["markets"]["total"]["data"]["current"]["first_side"]==1.6
    assert not x["official_fixed_bonus_verified"] and not x["can_use_for_production_betting"]
    sale={"source_policy":"USE_007_JC_AS_LOTTERY_PRICING_REFERENCE",
      "market_sale_status_notes":[{"date_beijing":"2026-10-31","game_id":"728165",
       "market":"win_lose","status":"NOT_ON_SALE_USER_CONFIRMED"}]}
    missing=b"$728165^1.7^1.7^-1.5^1.65^1.75^-3.5$728165^1.7^1.7^222.5^1.6^1.8^223.5"
    tagged=parse(missing,board,sale)
    assert tagged["matches"][0]["markets"]["win_lose"]["status"]=="NOT_ON_SALE_USER_CONFIRMED"
    assert tagged["007_jingcai_reference_user_confirmed"]
    assert not tagged["can_use_for_production_betting"]
    no_note=parse(missing,board,{"source_policy":"USE_007_JC_AS_LOTTERY_PRICING_REFERENCE"})
    assert no_note["matches"][0]["markets"]["win_lose"]["status"]=="NO_QUOTE_IN_007_FEED"
    assert all(item["status"]=="OBSERVED" for item in tagged["matches"][0]["markets"].values() if item.get("data"))
    try:parse(raw.replace(b"^-3.5",b"^"),board)
    except ValueError:pass
    else:raise AssertionError("MISSING_ODDS_WAS_ACCEPTED")
    print("JC_THREE_MARKET_FEED_SCHEMA_SELFTEST_PASS")

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--self-test",action="store_true")
    p.add_argument("--board")
    p.add_argument("--output")
    a=p.parse_args()
    if a.self_test:return self_test()
    if not a.board:raise SystemExit("REQUIRE_BOARD")
    rp,status=robots_policy()
    if rp is False or (rp is not None and not rp.can_fetch(UA,ORIGIN+PATH)):
        raise RuntimeError("ROBOTS_ACCESS_NOT_PERMITTED_"+status)
    board=json.loads(Path(a.board).read_text(encoding="utf-8"))
    result=parse(get_bytes(ORIGIN+PATH,300000),board)
    if a.output:Path(a.output).write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("JC_THREE_MARKET_REAL_DATA",json.dumps(result,ensure_ascii=False))

if __name__=="__main__":main()
