#!/usr/bin/env python3
"""Validate the REAL 007 Jingcai fixture number for the NBA board.

Do not derive the user-facing number from list position, commercial bookmaker
rows, or a guessed 300+ offset. An unmatched match is numbered 待核, never #01.
"""
from __future__ import annotations
import json,re
from datetime import datetime
from zoneinfo import ZoneInfo
from probe_007_jc_scripts import ORIGIN,UA,get_bytes,robots_policy
from verify_007_jc_fixture_identity import TARGET,MAX_BYTES,records,comparable

BJ=ZoneInfo("Asia/Shanghai")
CODE=re.compile(r"^(周[一二三四五六日天])(\d{3})$")

def verify(board,raw):
    feed=records(raw)
    games=[g for g in board.get("nba_cba_games",[]) if g.get("league")=="NBA"]
    day=str(board.get("requested_display_date") or "")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}",day):
        raise ValueError("BOARD_DATE_MISSING")
    output={};labels=set()
    for g in games:
        gid=str(g["game_id"])
        result={"game_id":gid,"status":"UNVERIFIED","label":None,"match_no":None}
        src=feed.get(gid)
        if src is None:result["reason"]="GAME_ID_NOT_IN_JC_FEED"
        elif not comparable(g.get("home_team",""),src.get("home_aliases",[])) or not comparable(g.get("away_team",""),src.get("away_aliases",[])):
            result["reason"]="HOME_AWAY_MISMATCH"
        else:
            code=CODE.fullmatch(src.get("match_label",""))
            if not code:result["reason"]="INVALID_JC_SALE_NUMBER"
            else:
                # Source time uses JS zero-indexed month; verify date and tipoff.
                raw_time=src.get("raw_time","")
                try:
                    parts=[int(x) for x in raw_time.split(",")[:6]]
                    assert len(parts)==6
                    year,zero_month,day_of_month,hour,minute,sec=parts
                    fixture_tip=datetime(year,zero_month+1,day_of_month,hour,minute,sec,tzinfo=BJ)
                    expected=datetime.fromisoformat(g["start_time_beijing"])
                    if expected.tzinfo is None:raise ValueError("NAIVE_TIPOFF")
                    delta=abs((fixture_tip-expected).total_seconds())
                except (ValueError,TypeError,KeyError,AssertionError) as exc:
                    result["reason"]="JC_FIXTURE_TIME_INVALID"
                else:
                    if delta>120*60:result["reason"]="JC_FIXTURE_TIME_MISMATCH"
                    else:
                        label=src["match_label"]
                        if label in labels:raise ValueError("DUPLICATE_JC_SALE_LABEL_"+label)
                        labels.add(label)
                        result.update({"status":"VERIFIED_JC_NUMBER","label":label,
                                       "match_no":code.group(2),"reason":None})
        output[gid]=result
    return {"source":ORIGIN+TARGET,"target_date_beijing":day,
      "status":"JC_MATCH_NUMBER_AUDIT","verified":sum(x["status"]=="VERIFIED_JC_NUMBER" for x in output.values()),
      "total_games":len(games),"games":output}

def live(board):
    rp,status=robots_policy()
    if rp is False or (rp is not None and not rp.can_fetch(UA,ORIGIN+TARGET)):
        raise RuntimeError("JC_FIXTURE_ACCESS_NOT_PERMITTED_"+status)
    return verify(board,get_bytes(ORIGIN+TARGET,MAX_BYTES))

def self_test():
    board={"requested_display_date":"2026-10-31","nba_cba_games":[
      {"game_id":"728165","league":"NBA","home_team":"华盛顿奇才",
       "away_team":"夏洛特黄蜂","start_time_beijing":"2026-10-31T07:00+08:00"},
      {"game_id":"728166","league":"NBA","home_team":"波士顿凯尔特人",
       "away_team":"芝加哥公牛","start_time_beijing":"2026-10-31T07:30+08:00"}]}
    raw=("1^meta$728165^2026,9,31,07,00,00^0^^周五309^7^11^华盛顿奇才,奇才^12^夏洛特黄蜂,黄蜂"
         "!728166^2026,9,31,07,30,00^0^^周五311^7^13^波士顿凯尔特人,凯尔特人^14^芝加哥公牛,公牛").encode()
    result=verify(board,raw)
    assert result["verified"]==2
    assert result["games"]["728165"]["label"]=="周五309"
    swapped=raw.replace("夏洛特黄蜂,黄蜂".encode(),"芝加哥公牛,公牛".encode(),1)
    assert verify(board,swapped)["games"]["728165"]["status"]=="UNVERIFIED"
    badtime=raw.replace(b"2026,9,31,07,00,00",b"2026,9,31,13,00,00")
    assert verify(board,badtime)["games"]["728165"]["reason"]=="JC_FIXTURE_TIME_MISMATCH"
    missing=verify(board,raw.split(b"!")[0])
    assert missing["games"]["728166"]["label"] is None
    print("JC_MATCH_NUMBERS_309_318_SELFTEST_PASS")
if __name__=="__main__":
    self_test()
