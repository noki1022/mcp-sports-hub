#!/usr/bin/env python3
"""Validate the REAL 007 Jingcai fixture number for the NBA board.

Do not derive the user-facing number from list position, commercial bookmaker
rows, or a guessed 300+ offset. An unmatched match is numbered 待核, never #01.
"""
from __future__ import annotations
import json,re
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from probe_007_jc_scripts import ORIGIN,UA,get_bytes,robots_policy
from verify_007_jc_fixture_identity import TARGET,MAX_BYTES,records,comparable

BJ=ZoneInfo("Asia/Shanghai")
CODE=re.compile(r"^(周[一二三四五六日天])(\d{3})$")

MANUAL_FILE=Path(__file__).resolve().parents[1]/"config"/"nba_jc_user_confirmed_numbers.json"

def manual_confirmations(path=MANUAL_FILE):
    """Human-confirmed DISPLAY-ONLY match labels. Never assert feed team
    identity, fixture reliability, market direction, or official odds."""
    if not path.is_file():return []
    doc=json.loads(path.read_text(encoding="utf-8"))
    if doc.get("schema_version")!="nba-jc-user-confirmed-number-display-v1":
        raise ValueError("UNRECOGNIZED_MANUAL_JC_NUMBER_SCHEMA")
    entries=doc.get("entries")
    if not isinstance(entries,list):raise ValueError("INVALID_USER_CONFIRMED_NUMBERS")
    seen=set()
    for item in entries:
        key=(str(item.get("target_date")),str(item.get("game_id")))
        if key in seen:raise ValueError("DUPLICATE_MANUAL_JC_GAME")
        seen.add(key)
        if (not CODE.fullmatch(str(item.get("label") or ""))
                or item.get("scope")!="MATCH_NUMBER_DISPLAY_ONLY"
                or item.get("price_side_identity_unaltered") is not True
                or not str(item.get("source") or "").startswith("USER_MANUAL_CONFIRMATION_")):
            raise ValueError("INVALID_MANUAL_JC_DISPLAY_ENTRY")
    return entries

def apply_manual_labels(board,output,labels,entries):
    day=str(board["requested_display_date"])
    games={str(g["game_id"]):g for g in board.get("nba_cba_games",[]) if g.get("league")=="NBA"}
    accepted=0
    for item in entries:
        if item["target_date"]!=day:continue
        gid=str(item["game_id"])
        g=games.get(gid)
        if g is None:raise ValueError("MANUAL_JC_GAME_ID_NOT_IN_EXACT_DAY_BOARD")
        # Full game identity INCLUDING start time must match. Never use a
        # number from similar names / guessed board position / another day.
        for key in ("nba_game_id","home_team","away_team","start_time_beijing"):
            v=item.get("tipoff_beijing") if key=="start_time_beijing" else item.get(key)
            if str(g.get(key))!=str(v):
                raise ValueError("MANUAL_JC_ID_HOME_AWAY_OR_TIPOFF_MISMATCH_"+key)
        row=output[gid]
        label=item["label"]
        if row["status"]=="VERIFIED_JC_NUMBER":
            if row["label"]!=label:raise ValueError("007_AND_USER_CONFIRMED_NUMBER_CONFLICT")
            continue
        # A later source outage must not erase the user's explicit display
        # correction or 14 independently verified labels. The source's
        # existing failure reason is retained, not upgraded to verified.
        original_reason=row.get("reason")
        if row["status"]!="UNVERIFIED" or not original_reason:
            raise ValueError("MANUAL_JC_NUMBER_NOT_AN_UNVERIFIED_NUMBER")
        if label in labels:raise ValueError("DUPLICATE_USER_AND_007_JC_NUMBER_"+label)
        labels.add(label)
        match=CODE.fullmatch(label)
        row.update({"status":"USER_CONFIRMED_JC_NUMBER","label":label,
                    "match_no":match.group(2),
                    "reason":"JC_SOURCE_UNVERIFIED_NUMBER_MANUALLY_CONFIRMED",
                    "original_007_identity_status":original_reason,
                    "number_source":item["source"],"number_only":True,
                    "fixture_home_away_verified":False,
                    "market_orientation_verified_by_manual_number":False})
        accepted+=1
    return accepted

def verify(board,raw,overrides=None):
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
    user_confirmed=apply_manual_labels(board,output,labels,
        manual_confirmations() if overrides is None else overrides)
    verified=sum(x["status"]=="VERIFIED_JC_NUMBER" for x in output.values())
    return {"source":ORIGIN+TARGET,"target_date_beijing":day,
      "status":"JC_MATCH_NUMBER_AUDIT",
      "verified":verified,"user_confirmed":user_confirmed,
      "numbered_total":verified+user_confirmed,
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
    # A user may explicitly resolve a single missing display number, but
    # a HOME_AWAY_MISMATCH must stay untrusted for market direction.
    user_board={"requested_display_date":"2026-11-03","nba_cba_games":[
      {"game_id":"728298","nba_game_id":"401909907","league":"NBA",
       "home_team":"克里夫兰骑士","away_team":"俄克拉荷马城雷霆",
       "start_time_beijing":"2026-11-03T08:00+08:00"}]}
    wrong=("1^meta$728298^2026,10,3,08,00,00^0^^周一302^7^11^"
           "俄克拉荷马城雷霆,雷霆^12^克里夫兰骑士,骑士").encode()
    unverified=verify(user_board,wrong,overrides=[])
    assert unverified["games"]["728298"]["reason"]=="HOME_AWAY_MISMATCH"
    item={"target_date":"2026-11-03","game_id":"728298",
          "nba_game_id":"401909907","home_team":"克里夫兰骑士",
          "away_team":"俄克拉荷马城雷霆",
          "tipoff_beijing":"2026-11-03T08:00+08:00",
          "label":"周一302","source":"USER_MANUAL_CONFIRMATION_2026_11_02",
          "scope":"MATCH_NUMBER_DISPLAY_ONLY","price_side_identity_unaltered":True}
    user=verify(user_board,wrong,overrides=[item])
    x=user["games"]["728298"]
    assert x["status"]=="USER_CONFIRMED_JC_NUMBER" and x["label"]=="周一302"
    assert user["verified"]==0 and user["user_confirmed"]==1
    assert x["fixture_home_away_verified"] is False
    assert x["original_007_identity_status"]=="HOME_AWAY_MISMATCH"
    unavailable=verify(user_board,"1^meta$999999^2026,10,3,08,00,00^0^^周一320^7^11^X^12^Y".encode(),
                       overrides=[item])
    assert unavailable["games"]["728298"]["label"]=="周一302"
    assert unavailable["games"]["728298"]["original_007_identity_status"]=="GAME_ID_NOT_IN_JC_FEED"
    try:
        verify(user_board,wrong,overrides=[dict(item,home_team="其他球队")])
    except ValueError as e:assert "MISMATCH" in str(e)
    else:raise AssertionError("FORGED_MANUAL_TEAM_IDENTITY_ACCEPTED")
    # Also test that a legitimately verified but conflicting number cannot
    # be silently overwritten by a manual entry.
    correct=wrong.replace("俄克拉荷马城雷霆,雷霆^12^克里夫兰骑士,骑士".encode(),
        "克里夫兰骑士,骑士^12^俄克拉荷马城雷霆,雷霆".encode())
    try:verify(user_board,correct,overrides=[dict(item,label="周一303")])
    except ValueError as e:assert "CONFLICT" in str(e)
    else:raise AssertionError("SOURCE_VS_MANUAL_LABEL_CONFLICT_SILENCED")
    print("JC_MANUAL_302_ONLY_NUMBER_NOT_MARKET_IDENTITY_SELFTEST_PASS")
    print("JC_MATCH_NUMBERS_309_318_SELFTEST_PASS")
if __name__=="__main__":
    self_test()
