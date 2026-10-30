#!/usr/bin/env python3
"""Exact ID+team audit of public 007 JC *fixture* text against verified NBA board.

The JC feed is !/$/^ delimited. A textual ID substring is NOT proof of a match:
require record-id position AND correct home/away aliases before accepting.
No fixed award, water orientation, or production pricing is inferred.
"""
import argparse,json,re
from pathlib import Path
from probe_007_jc_scripts import ORIGIN,UA,get_bytes,robots_policy

TARGET="/xml/bf_jc_lq.txt"
MAX_BYTES=350000

def records(raw):
    decoded=None
    for enc in ("utf-8-sig","gb18030"):
        try:decoded=raw.decode(enc);break
        except UnicodeDecodeError:continue
    if decoded is None:raise ValueError("FEED_ENCODING_UNKNOWN")
    found={}
    for chunk in decoded.split("$")[1:]:
        f=chunk.split("^")
        game_id=f[0].strip() if f else ""
        if not re.fullmatch(r"\d{4,12}",game_id):continue
        if game_id in found:raise ValueError("DUPLICATE_RECORD_ID")
        # layout observed in first feed record: id, time, state, '', matchNo,
        # competitionId, homeId, homeAliases, awayId, awayAliases...
        if len(f)<10:continue
        found[game_id]={"id":game_id,"raw_time":f[1],
          "home_aliases":f[7].split(","),"away_aliases":f[9].split(","),
          "raw_field_count":len(f)}
    return found

def comparable(name,aliases):
    # Require a full alias equality or a clear, nontrivial short team-name suffix;
    # never accept generic substrings, and never swap home/away silently.
    def norm(s):return re.sub(r"[\s\[\]()（）]+","",s.strip().lower())
    name=norm(name)
    for alias in aliases:
        alias=norm(alias)
        if not alias:continue
        if name==alias:return True
        if len(alias)>=2 and name.endswith(alias) and len(name)-len(alias)<=5:return True
        if len(name)>=2 and alias.endswith(name) and len(alias)-len(name)<=5:return True
    return False

def reconcile(raw,board):
    feed=records(raw)
    games=board.get("nba_cba_games",[])
    if not games:raise ValueError("NO_REFERENCE_GAMES")
    audit=[]
    for game in games:
        gid=str(game["game_id"])
        row=feed.get(gid)
        status="NO_EXACT_RECORD_ID"
        if row:
            home=comparable(game["home_team"],row["home_aliases"])
            away=comparable(game["away_team"],row["away_aliases"])
            status="ID_AND_TEAM_ORDER_MATCH" if home and away else "TEAM_IDENTITY_NOT_VERIFIED"
        audit.append({"game_id":gid,"nba_game_id":game.get("nba_game_id"),
          "home_team":game["home_team"],"away_team":game["away_team"],
          "status":status,"raw_fixture_time":row["raw_time"] if row else None})
    return {"schema_version":"007-jc-public-fixture-id-audit-v1",
      "source":ORIGIN+TARGET,"date":board.get("requested_display_date"),
      "reference_games":len(games),"public_fixture_records":len(feed),
      "confirmed_id_and_home_away":sum(x["status"]=="ID_AND_TEAM_ORDER_MATCH" for x in audit),
      "unconfirmed_count":sum(x["status"]!="ID_AND_TEAM_ORDER_MATCH" for x in audit),
      "betting_prices_verified":0,"official_fixed_payout_verified":False,
      "model_fusion_enabled":False,"games":audit}

def fetch_and_compare(board):
    rp,status=robots_policy()
    if rp is False:raise RuntimeError("ROBOTS_UNAVAILABLE_OR_DENIED_"+status)
    if rp is not None and not rp.can_fetch(UA,ORIGIN+TARGET):
        raise RuntimeError("ROBOTS_DISALLOW")
    raw=get_bytes(ORIGIN+TARGET,MAX_BYTES)
    return reconcile(raw,board)

def self_test():
    sample=("1^#FF0000^NBA,NBA^1^4$728165^2026,9,31,07,00,00^0^^周五309^7^11^"
      "华盛顿奇才,奇才^12^夏洛特黄蜂,黄蜂^0^0^0^0$728166^2026,9,31,07,30,00"
      "^0^^周五311^7^13^波士顿凯尔特人,凯尔特人^14^芝加哥公牛,公牛^0^0$")
    board={"requested_display_date":"2026-10-31",
      "nba_cba_games":[{"game_id":"728165","nba_game_id":"401909277",
       "home_team":"华盛顿奇才","away_team":"夏洛特黄蜂"},
       {"game_id":"728166","nba_game_id":"401909278",
       "home_team":"波士顿凯尔特人","away_team":"芝加哥公牛"}]}
    good=reconcile(sample.encode(),board)
    assert good["confirmed_id_and_home_away"]==2
    swapped=sample.replace("华盛顿奇才,奇才^12^夏洛特黄蜂,黄蜂",
                           "夏洛特黄蜂,黄蜂^12^华盛顿奇才,奇才")
    bad=reconcile(swapped.encode(),board)
    assert bad["confirmed_id_and_home_away"]==1
    assert bad["games"][0]["status"]=="TEAM_IDENTITY_NOT_VERIFIED"
    assert not good["model_fusion_enabled"] and good["betting_prices_verified"]==0
    print("JC_EXACT_GAME_ID_AND_TEAM_ORDER_TEST_PASS")

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--board")
    p.add_argument("--out")
    p.add_argument("--self-test",action="store_true")
    a=p.parse_args()
    if a.self_test:self_test()
    else:
        if not a.board:raise SystemExit("REQUIRES_BOARD")
        result=fetch_and_compare(json.loads(Path(a.board).read_text(encoding="utf-8")))
        if a.out:Path(a.out).write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        print("JC_IDENTITY_RECONCILIATION",json.dumps(result,ensure_ascii=False))
