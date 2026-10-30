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
    # $ divides league metadata from match records; ! separates match rows.
    # Splitting on $ alone collapses all games into one false record.
    payload=decoded.partition("$")[2]
    if not payload:raise ValueError("MISSING_FIXTURE_DATA_SECTION")
    for chunk in payload.split("!"):
        f=chunk.split("^")
        game_id=f[0].strip() if f else ""
        if not re.fullmatch(r"\d{4,12}",game_id):continue
        if game_id in found:raise ValueError("DUPLICATE_RECORD_ID")
        # layout observed in first feed record: id, time, state, '', matchNo,
        # competitionId, homeId, homeAliases, awayId, awayAliases...
        if len(f)<10:continue
        found[game_id]={"id":game_id,"raw_time":f[1],
          "home_aliases":f[7].split(","),"away_aliases":f[9].split(","),
          "match_label":f[4].strip(),
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

def reconcile(raw,board,screen=None):
    # Diagnostic: count raw separators and exact-ID occurrences; do not
    # interpret substring presence as a structural record.
    decoded=raw.decode("utf-8-sig","replace")
    raw_diagnostic={"dollar_count":decoded.count("$"),
        "exclamation_count":decoded.count("!"),
        "caret_count":decoded.count("^"),
        "byte_count":len(raw),
        "expected_id_occurrences":{str(x["game_id"]):len(re.findall(r"(?<!\\d)"+re.escape(str(x["game_id"]))+r"(?!\\d)",decoded))
                                   for x in board.get("nba_cba_games",[])}}
    feed=records(raw)
    games=board.get("nba_cba_games",[])
    if not games:raise ValueError("NO_REFERENCE_GAMES")
    audit=[]
    screenshot_by_team = []
    if screen is not None:
        if screen.get("source") != "USER_SUPPLIED_007_SCREENSHOT" or screen.get("source_is_official") is not False:
            raise ValueError("UNVERIFIED_SCREENSHOT_SOURCE")
        if board.get("requested_display_date") not in screen.get("display_window",""):
            raise ValueError("SCREENSHOT_DATE_WINDOW_MISMATCH")
        screenshot_by_team = screen.get("rows",[])
        if len({str(item.get("match_no")) for item in screenshot_by_team}) != len(screenshot_by_team):
            raise ValueError("DUPLICATE_SCREENSHOT_MATCH_NUMBER")
    for game in games:
        gid=str(game["game_id"])
        row=feed.get(gid)
        status="NO_EXACT_RECORD_ID"
        if row:
            home=comparable(game["home_team"],row["home_aliases"])
            away=comparable(game["away_team"],row["away_aliases"])
            status="ID_AND_TEAM_ORDER_MATCH" if home and away else "TEAM_IDENTITY_NOT_VERIFIED"
        price_number_status="NOT_CHECKED"
        raw_label=row.get("match_label","") if row else ""
        screenshot_matches=[item for item in screenshot_by_team
            if comparable(game["home_team"],[item.get("home","")])
            and comparable(game["away_team"],[item.get("away","")])]
        screenshot_no=None
        if screen is not None:
            if len(screenshot_matches)!=1:
                price_number_status="SCREENSHOT_TEAM_IDENTITY_UNMATCHED"
            else:
                screenshot_no=str(screenshot_matches[0]["match_no"])
                found=re.search(r"(?<!\\d)(\\d{3})(?!\\d)$",raw_label)
                if status!="ID_AND_TEAM_ORDER_MATCH":
                    price_number_status="FIXTURE_ID_OR_TEAM_NOT_VERIFIED"
                elif found is None:
                    price_number_status="PUBLIC_FEED_MATCH_NUMBER_MISSING"
                elif found.group(1)!=screenshot_no:
                    price_number_status="JINGCAI_MATCH_NUMBER_CONFLICT"
                else:
                    price_number_status="THIRD_PARTY_MATCH_NUMBER_ALIGNED"
        audit.append({"game_id":gid,"nba_game_id":game.get("nba_game_id"),
          "home_team":game["home_team"],"away_team":game["away_team"],
          "status":status,"raw_fixture_time":row["raw_time"] if row else None,
          "public_fixture_match_label":raw_label,"screenshot_match_no":screenshot_no,
          "match_number_crosscheck":price_number_status})
    return {"schema_version":"007-jc-public-fixture-id-audit-v1",
      "source":ORIGIN+TARGET,"date":board.get("requested_display_date"),
      "reference_games":len(games),"public_fixture_records":len(feed),"raw_structure":raw_diagnostic,
      "confirmed_id_and_home_away":sum(x["status"]=="ID_AND_TEAM_ORDER_MATCH" for x in audit),
      "unconfirmed_count":sum(x["status"]!="ID_AND_TEAM_ORDER_MATCH" for x in audit),
      "confirmed_public_match_number_alignment":sum(x["match_number_crosscheck"]=="THIRD_PARTY_MATCH_NUMBER_ALIGNED" for x in audit),
      "match_number_conflicts":sum(x["match_number_crosscheck"]=="JINGCAI_MATCH_NUMBER_CONFLICT" for x in audit),
      "betting_prices_verified":0,"official_fixed_payout_verified":False,
      "model_fusion_enabled":False,"games":audit}

def fetch_and_compare(board,screen=None):
    rp,status=robots_policy()
    if rp is False:raise RuntimeError("ROBOTS_UNAVAILABLE_OR_DENIED_"+status)
    if rp is not None and not rp.can_fetch(UA,ORIGIN+TARGET):
        raise RuntimeError("ROBOTS_DISALLOW")
    raw=get_bytes(ORIGIN+TARGET,MAX_BYTES)
    return reconcile(raw,board,screen)

def self_test():
    sample=("1^#FF0000^NBA,NBA^1^4$728165^2026,9,31,07,00,00^0^^周五309^7^11^"
      "华盛顿奇才,奇才^12^夏洛特黄蜂,黄蜂^0^0^0^0!728166^2026,9,31,07,30,00"
      "^0^^周五311^7^13^波士顿凯尔特人,凯尔特人^14^芝加哥公牛,公牛^0^0$")
    board={"requested_display_date":"2026-10-31",
      "nba_cba_games":[{"game_id":"728165","nba_game_id":"401909277",
       "home_team":"华盛顿奇才","away_team":"夏洛特黄蜂"},
       {"game_id":"728166","nba_game_id":"401909278",
       "home_team":"波士顿凯尔特人","away_team":"芝加哥公牛"}]}
    good=reconcile(sample.encode(),board)
    assert good["confirmed_id_and_home_away"]==2
    assert good["games"][0]["public_fixture_match_label"]=="周五309"
    swapped=sample.replace("华盛顿奇才,奇才^12^夏洛特黄蜂,黄蜂",
                           "夏洛特黄蜂,黄蜂^12^华盛顿奇才,奇才")
    bad=reconcile(swapped.encode(),board)
    assert bad["confirmed_id_and_home_away"]==1
    assert bad["games"][0]["status"]=="TEAM_IDENTITY_NOT_VERIFIED"
    assert not good["model_fusion_enabled"] and good["betting_prices_verified"]==0
    screenshot={"source":"USER_SUPPLIED_007_SCREENSHOT","source_is_official":False,
      "display_window":"2026-10-30 12:00 through 2026-10-31 12:00",
      "rows":[{"match_no":"309","home":"奇才","away":"黄蜂"},
              {"match_no":"311","home":"凯尔特人","away":"公牛"}]}
    matched=reconcile(sample.encode(),board,screenshot)
    assert matched["confirmed_public_match_number_alignment"]==2
    mismatch=json.loads(json.dumps(screenshot))
    mismatch["rows"][0]["match_no"]="310"
    rejected=reconcile(sample.encode(),board,mismatch)
    assert rejected["match_number_conflicts"]==1
    assert not rejected["model_fusion_enabled"]
    print("JC_EXACT_GAME_ID_AND_TEAM_ORDER_TEST_PASS")

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--board")
    p.add_argument("--screen")
    p.add_argument("--out")
    p.add_argument("--self-test",action="store_true")
    a=p.parse_args()
    if a.self_test:self_test()
    else:
        if not a.board:raise SystemExit("REQUIRES_BOARD")
        board=json.loads(Path(a.board).read_text(encoding="utf-8"))
        screen=json.loads(Path(a.screen).read_text(encoding="utf-8")) if a.screen else None
        result=fetch_and_compare(board,screen)
        if a.out:Path(a.out).write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        print("JC_IDENTITY_RECONCILIATION",json.dumps(result,ensure_ascii=False))
