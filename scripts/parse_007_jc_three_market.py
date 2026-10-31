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
    rejected_counts={}
    rejected_game_ids={}
    for market,part in zip(MARKETS,parts):
        rows={}
        rejected={}
        bad_ids=set()
        seen_ids=set()
        raw_records=0
        for entry in part.split("!"):
            if not entry.strip():continue
            raw_records+=1
            a=entry.split("^")
            gid=a[0] if a and re.fullmatch(r"\\d{4,12}",a[0]) else None
            if gid is not None and gid in seen_ids:
                # Never accept an arbitrary first or last quote for a duplicate ID.
                rows.pop(gid,None)
                bad_ids.add(gid)
                rejected["DUPLICATE_ID"] = rejected.get("DUPLICATE_ID",0)+1
                continue
            if gid is not None:seen_ids.add(gid)
            if gid in bad_ids:continue
            reason=None
            if gid is None or len(a)!=7:
                reason="INVALID_ROW_FORMAT"
            else:
                vals=list(map(number,a[1:]))
                if any(x is None for x in vals):
                    reason="MISSING_OR_NONFINITE_PRICE"
                else:
                    first_a,first_b,first_line,last_a,last_b,last_line=vals
                    if not all(1<x<30 for x in (first_a,first_b,last_a,last_b)):
                        reason="PRICE_OUT_OF_RANGE"
                    elif market=="win_lose" and (first_line!=0 or last_line!=0):
                        reason="UNEXPECTED_WIN_LINE"
                    elif market=="total" and not (80<=first_line<=400 and 80<=last_line<=400):
                        reason="TOTAL_LINE_OUT_OF_RANGE"
                    elif market=="handicap" and not (-80<=first_line<=80 and -80<=last_line<=80):
                        reason="HANDICAP_LINE_OUT_OF_RANGE"
            if reason:
                rejected[reason]=rejected.get(reason,0)+1
                if gid:bad_ids.add(gid)
                continue
            if market=="win_lose":
                opening={"first_side":first_a,"second_side":first_b}
                current={"first_side":last_a,"second_side":last_b}
            else:
                opening={"line":first_line,"first_side":first_a,"second_side":first_b}
                current={"line":last_line,"first_side":last_a,"second_side":last_b}
            rows[gid]={"opening":opening,"current":current,"line_or_odds_changed":opening!=current}
        if raw_records and not rows:
            # A wholly invalid nonempty section is a possible schema change,
            # never silently interpret it as a bookmaker-wide closure.
            raise ValueError("ALL_"+market.upper()+"_ROWS_REJECTED")
        tables[market]=rows
        rejected_counts[market]=rejected
        rejected_game_ids[market]=sorted(bad_ids)
    result={"captured_at_utc":datetime.now(timezone.utc).isoformat(),
            "origin":"007_THIRD_PARTY_JC_PUBLIC_XML","url":ORIGIN+PATH,
            "date_beijing":board.get("requested_display_date"),
            "market_ids":MARKET_ID,
            "source_record_counts":{k:len(v) for k,v in tables.items()},
            "source_rejected_counts":rejected_counts,
            "source_rejected_game_ids":rejected_game_ids,
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
                        else ({"status":"SOURCE_ROW_REJECTED"} if gid in rejected_game_ids[m]
                              else {"status":"NOT_ON_SALE_USER_CONFIRMED","evidence":"EXPLICIT_USER_CONFIRMATION"}
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
    # Fault injection: one corrupted game never destroys other valid rows.
    second=b"728166^1.7^1.8^0^1.72^1.77^0"
    two=raw.replace(b"$",b"!"+second+b"$",1).replace(b"$",b"!728166^1.7^1.7^-2.5^1.75^1.65^-3.5$",1)
    corrupt=two.replace(b"728165^1.7^1.7^-1.5",b"728165^1.7^1.7^")
    results=parse(corrupt,board)
    assert results["matches"][0]["markets"]["win_lose"]["status"]=="OBSERVED"
    assert results["matches"][0]["markets"]["handicap"]["status"]=="SOURCE_ROW_REJECTED"
    assert results["matches"][0]["markets"]["total"]["status"]=="OBSERVED"
    assert results["source_rejected_counts"]["handicap"]["MISSING_OR_NONFINITE_PRICE"]==1
    # Same-ID collisions must not silently keep the first quote.
    collision=raw.replace(b"$",b"!728165^1.8^1.9^0^1.8^1.9^0$",1)
    try:parse(collision,board)
    except ValueError as exc:assert "ALL_WIN_LOSE_ROWS_REJECTED" in str(exc)
    else:raise AssertionError("DUPLICATE_ID_ACCEPTED")
    try:parse(b"not a three market format",board)
    except ValueError as exc:assert "EXPECTED_THREE" in str(exc)
    else:raise AssertionError("SCHEMA_DRIFT_ACCEPTED")
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
