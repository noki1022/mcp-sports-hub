#!/usr/bin/env python3
"""Validate manually transcribed 007 Jingcai screenshots as third-party snapshot evidence.

This is NOT a website scraper and never claims official lottery payout verification.
"""
import argparse,json,math
from datetime import datetime
from pathlib import Path

def verify(payload):
    if payload.get("source")!="USER_SUPPLIED_007_SCREENSHOT":
        raise ValueError("INVALID_SOURCE")
    if payload.get("source_is_official") is not False:
        raise ValueError("OFFICIALITY_NOT_DECLARED")
    if not payload.get("display_window"):raise ValueError("MISSING_DISPLAY_WINDOW")
    rows=payload.get("rows")
    if not isinstance(rows,list) or not rows:raise ValueError("EMPTY_ROWS")
    unique=set()
    for row in rows:
        mid=str(row.get("match_no",""))
        if not mid.isdigit() or mid in unique:raise ValueError("BAD_OR_DUPLICATE_MATCH_NO")
        unique.add(mid)
        if not row.get("league") or not row.get("home") or not row.get("away"):
            raise ValueError("MISSING_GAME_IDENTITIES")
        for market in ("total","handicap","win_loss"):
            quote=row.get(market)
            if quote is None:continue
            if quote.get("source")!="007_JINGCAI_DISPLAY":
                raise ValueError("MARKET_SOURCE_UNVERIFIED")
            if quote.get("selection_order") not in ("LABELED","UNVERIFIED"):
                raise ValueError("SELECTION_ORDER_MISSING")
            sides=("over","under") if market=="total" else ("home","away")
            for side in sides:
                x=quote.get(side)
                if not isinstance(x,(int,float)) or not math.isfinite(x) or not 1<x<1000:
                    raise ValueError("INVALID_PRICE")
            if market in ("total","handicap"):
                k=quote.get("line")
                if not isinstance(k,(int,float)) or not math.isfinite(k):
                    raise ValueError("INVALID_LINE")
    payload["verified_as"]="MANUAL_TRANSCRIPTION_SCHEMA_VALID_ONLY"
    payload["live_verified"]=False
    payload["official_payout_verified"]=False
    return payload

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--infile")
    p.add_argument("--outfile")
    p.add_argument("--self-test",action="store_true")
    a=p.parse_args()
    if a.self_test:
        fixture={"source":"USER_SUPPLIED_007_SCREENSHOT","source_is_official":False,
                 "display_window":"2026-10-30 12:00 to 2026-10-31 12:00",
                 "rows":[{"match_no":"309","league":"NBA","home":"奇才","away":"黄蜂",
                          "total":{"source":"007_JINGCAI_DISPLAY","selection_order":"LABELED",
                                   "line":221.5,"over":1.62,"under":1.78}}]}
        verify(fixture)
        assert fixture["official_payout_verified"] is False
        fixture["rows"].append(dict(fixture["rows"][0]))
        try:verify(fixture)
        except ValueError as ex:assert str(ex)=="BAD_OR_DUPLICATE_MATCH_NO"
        else:raise AssertionError("DUPLICATE_NOT_REJECTED")
        print("007_USER_SNAPSHOT_VALIDATOR_PASS")
    else:
        if not a.infile or not a.outfile:raise SystemExit("INFILE_OUTFILE_REQUIRED")
        data=verify(json.loads(Path(a.infile).read_text(encoding="utf-8")))
        Path(a.outfile).write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
if __name__=="__main__":main()
