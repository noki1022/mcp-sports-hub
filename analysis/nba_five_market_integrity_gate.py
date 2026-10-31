#!/usr/bin/env python3
"""Strict pre-send P0 007 fixture/market-source integrity gate.

Markets may legitimately be missing during Crown suspension; only issued
directions are subject to point-in-time and symbol assertions. Do not infer
Jingcai sale identity from the 007 fixture ID.
"""
from __future__ import annotations
import argparse,json,math,re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

BJ=ZoneInfo("Asia/Shanghai")
KEYS=("JINGCAI_WIN","JINGCAI_HANDICAP","JINGCAI_TOTAL","CROWN_HANDICAP","CROWN_TOTAL")
DIRECTIONS={
"JINGCAI_WIN":("HOME_WIN","AWAY_WIN"),"JINGCAI_HANDICAP":("HOME_COVER","AWAY_COVER"),
"JINGCAI_TOTAL":("OVER","UNDER"),"CROWN_HANDICAP":("HOME_COVER","AWAY_COVER"),
"CROWN_TOTAL":("OVER","UNDER")}
def real(x):
    if isinstance(x,bool) or x is None:return None
    try:
        a=float(x)
        return a if math.isfinite(a) else None
    except (ValueError,TypeError):return None
def dt(x):
    try:
        a=datetime.fromisoformat(str(x).replace("Z","+00:00"))
        return a if a.tzinfo is not None else None
    except (TypeError,ValueError):return None
def same(a,b,tol=1e-6):return a is not None and b is not None and abs(a-b)<=tol
def verify(joined,five,jc=None):
    board=[g for g in joined.get("nba_cba_games",[]) if g.get("league")=="NBA"]
    rows=five.get("games",[])
    failures=[]
    def bad(tag,game):failures.append({"game_id":str(game),"reason":tag})
    ids=[str(g.get("game_id") or "") for g in board]
    if not board or not all(ids) or len(set(ids))!=len(ids):bad("BAD_OR_DUPLICATE_007_BOARD_ID","BOARD")
    board_idx={str(g.get("game_id")):g for g in board}
    fid=[str(g.get("game_id") or "") for g in rows]
    if not rows or not all(fid) or len(set(fid))!=len(fid) or set(fid)!=set(ids):bad("FIVE_BOARD_ID_MISMATCH","BOARD")
    if five.get("target_date")!=joined.get("requested_display_date"):bad("BEIJING_DATE_MISMATCH","BOARD")
    jc_ids=((jc or {}).get("jc_007_match_numbers") or {}).get("games") or {}
    labeled=set()
    for row in rows:
        game=str(row.get("game_id"))
        b=board_idx.get(game)
        if not b:continue
        for key in ("nba_game_id","home_team","away_team"):
            if not b.get(key) or str(row.get(key) or "")!=str(b.get(key)):bad("FIXTURE_ID_OR_HOME_AWAY_MISMATCH_"+key,game)
        tip=dt(b.get("start_time_beijing"))
        if tip is None or tip.astimezone(BJ).date().isoformat()!=five.get("target_date"):bad("TIPOFF_DATE_NOT_VERIFIED",game)
        if dt(row.get("tipoff_beijing"))!=tip:bad("FROZEN_TIPOFF_MISMATCH",game)
        label=row.get("jingcai_number")
        if label is not None:
            if not re.fullmatch(r"周[一二三四五六日天]\d{3}",str(label)):bad("INVALID_JINGCAI_LABEL",game)
            if label in labeled:bad("DUPLICATE_JINGCAI_LABEL",game)
            labeled.add(label)
            proof=jc_ids.get(game) or {}
            if jc is not None and (proof.get("status")!="VERIFIED_JC_NUMBER" or label!=proof.get("label")):
                bad("JINGCAI_LABEL_PROOF_MISMATCH",game)
        markets=row.get("markets") or {}
        if set(markets)!=set(KEYS):bad("FIVE_MARKET_KEYS_MISSING",game);continue
        for key in KEYS:
            m=markets[key];direction=m.get("direction")
            if m.get("market")!=key:bad("MARKET_TYPE_MISMATCH_"+key,game)
            if m.get("status")!="DIRECTION_ISSUED":
                if direction is not None:bad("UNVERIFIED_DIRECTION_"+key,game)
                continue
            if direction not in DIRECTIONS[key]:bad("INVALID_DIRECTION_"+key,game);continue
            captured=dt(m.get("captured_at_utc"))
            if captured is None or tip is None or captured>=tip:bad("NON_PRETIP_SOURCE_"+key,game)
            line=real(m.get("line"))
            if key!="JINGCAI_WIN" and line is None:bad("MISSING_MARKET_LINE_"+key,game);continue
            if key.startswith("JINGCAI_"):
                if m.get("source")!="007_JINGCAI":bad("JINGCAI_WRONG_SOURCE_"+key,game)
            else:
                if m.get("source") not in ("007_CROWN_ID3","007_CROWN_ID3_ARCHIVED_PRETIP") or str(m.get("source_id"))!="3":
                    bad("CROWN_NOT_ID3_"+key,game)
            if key.endswith("HANDICAP"):
                expected=line if key=="JINGCAI_HANDICAP" else -line
                if not same(real(m.get("signed_home_handicap")),expected):
                    bad("HOME_HANDICAP_SIGN_INVERTED_"+key,game)
            if key.endswith("TOTAL") and not (80<=line<=400):bad("INVALID_TOTAL_THRESHOLD_"+key,game)
            if key in ("JINGCAI_HANDICAP","JINGCAI_TOTAL","CROWN_HANDICAP","CROWN_TOTAL"):
                val=real(row.get("model_margin_home_minus_away" if key.endswith("HANDICAP") else "model_total"))
                if val is not None:
                    gap=val+(line if key=="JINGCAI_HANDICAP" else -line) if key.endswith("HANDICAP") else val-line
                    intended=("HOME_COVER" if gap>0 else "AWAY_COVER") if key.endswith("HANDICAP") else ("OVER" if gap>0 else "UNDER")
                    if abs(gap)>1e-6 and direction!=intended:bad("MODEL_VERSUS_LINE_DIRECTION_MISMATCH_"+key,game)
    return {"status":"PASS" if not failures else "BLOCK","games":len(rows),"failures":failures}
def selftest():
    board={"requested_display_date":"2026-11-01","nba_cba_games":[{"game_id":"123","nba_game_id":"401","league":"NBA",
          "home_team":"主","away_team":"客","start_time_beijing":"2026-11-01T08:00:00+08:00"}]}
    t="2026-10-31T20:00:00+08:00"
    def m(k,direction,line,handicap=None):
        return {"market":k,"status":"DIRECTION_ISSUED","direction":direction,"line":line,
                "signed_home_handicap":handicap,"source":"007_JINGCAI" if k.startswith("JINGCAI") else "007_CROWN_ID3",
                "source_id":"3" if k.startswith("CROWN") else None,"captured_at_utc":t}
    games=[{"game_id":"123","nba_game_id":"401","home_team":"主","away_team":"客","tipoff_beijing":"2026-11-01T08:00:00+08:00",
      "jingcai_number":"周六316","model_margin_home_minus_away":2,"model_total":230,
      "markets":{"JINGCAI_WIN":m("JINGCAI_WIN","HOME_WIN",None),
                 "JINGCAI_HANDICAP":m("JINGCAI_HANDICAP","AWAY_COVER",-5.5,-5.5),
                 "JINGCAI_TOTAL":m("JINGCAI_TOTAL","UNDER",232),
                 "CROWN_HANDICAP":m("CROWN_HANDICAP","HOME_COVER",-1.5,1.5),
                 "CROWN_TOTAL":m("CROWN_TOTAL","OVER",225)}}]
    five={"target_date":"2026-11-01","games":games}
    jc={"jc_007_match_numbers":{"games":{"123":{"label":"周六316","status":"VERIFIED_JC_NUMBER"}}}}
    assert verify(board,five,jc)["status"]=="PASS"
    games[0]["home_team"]="客"
    assert verify(board,five,jc)["status"]=="BLOCK";games[0]["home_team"]="主"
    games[0]["markets"]["CROWN_HANDICAP"]["signed_home_handicap"]=-1.5
    assert any("SIGN_INVERTED" in x["reason"] for x in verify(board,five,jc)["failures"])
    games[0]["markets"]["CROWN_HANDICAP"]["signed_home_handicap"]=1.5
    games[0]["jingcai_number"]="周六315"
    assert any("LABEL_PROOF" in x["reason"] for x in verify(board,five,jc)["failures"])
    print("P0_FIVE_MARKET_POINT_IN_TIME_IDENTITY_SYMBOL_TEST_PASS")
if __name__=="__main__":
    p=argparse.ArgumentParser()
    for key in ("joined","five","jingcai","out"):p.add_argument("--"+key)
    p.add_argument("--self-test",action="store_true")
    args=p.parse_args()
    if args.self_test:selftest()
    else:
        if not args.joined or not args.five:raise SystemExit("P0_INPUT_MISSING")
        load=lambda path:json.loads(Path(path).read_text())
        result=verify(load(args.joined),load(args.five),load(args.jingcai) if args.jingcai else None)
        if args.out:Path(args.out).write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
        print("P0_007_FIVE_MARKET_GATE",result["status"],len(result["failures"]))
        if result["status"]!="PASS":raise SystemExit(2)
