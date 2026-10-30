#!/usr/bin/env python3
"""Audit 007 JC side direction from 007 client code and user-supplied labeled total quote.

Validates source code *semantics*, not equality of all bookmaker and lottery
prices. 007 odds are user-approved lottery-price reference; actual payouts
can still vary between snapshots. Refuse ambiguous or mismatched evidence.
"""
from __future__ import annotations
import argparse,json,re
from pathlib import Path
from probe_007_jc_scripts import ORIGIN,UA,get_bytes,robots_policy
from parse_007_jc_three_market import parse

COMMON="/js/common.js"
BASKET="/js/basket.js"
ODDS="/xml/odds_jc_lq.txt"
TEST_ID="728173" # 007 #317 Warriors vs Lakers in user's labeled total screenshot

def evidence(common,basket,raw,board,screen):
    c=common.decode("utf-8-sig","replace")
    b=basket.decode("utf-8-sig","replace")
    # Extract from 007 source, not guessed numerical comparison.
    checks={
      "basketball_first_field_is_home":bool(re.search(
        r"_glJC\.jcOddsLq\s*=\s*function[\s\S]{0,400}?this\.homeWin_f\s*=\s*arr\[1\]",c)),
      "basketball_second_field_is_away":bool(re.search(
        r"_glJC\.jcOddsLq\s*=\s*function[\s\S]{0,400}?this\.guestWin_f\s*=\s*arr\[2\]",c)),
      "basketball_live_first_home":bool(re.search(r"this\.homeWin\s*=\s*arr\[indexNum\]",c)),
      "basketball_live_second_away":bool(re.search(r"this\.guestWin\s*=\s*arr\[indexNum\s*\+\s*1\]",c)),
      "html_first_price_home_column":bool(re.search(r"<td class=\\?['\"]H_Odd[\s\S]{0,200}?homeWin",b)),
      "html_second_price_away_column":bool(re.search(r"<td class=\\?['\"]G_Odd[\s\S]{0,200}?guestWin",b)),
      "market_111_112_114_explicit":all(re.search(r"\b"+s+r"\b",c) for s in ("111","112","114")),
    }
    data=parse(raw,board)
    games={str(g["game_id"]):g for g in data["matches"]}
    target=games.get(TEST_ID)
    if target is None:raise ValueError("SCREENSHOT_MATCH_NOT_IN_007_BOARD")
    screenshot=[x for x in screen.get("rows",[]) if x.get("match_no")=="317" and x.get("home")=="勇士" and x.get("away")=="湖人"]
    if len(screenshot)!=1:raise ValueError("NO_LABELED_TOTAL_SCREENSHOT_317")
    quote=screenshot[0].get("total") or {}
    if quote.get("selection_order")!="LABELED":raise ValueError("SCREENSHOT_NOT_LABELED")
    observed=(target["markets"]["total"].get("data") or {})
    # Screenshot and feed may have different timestamps; compare with either stored
    # opening or current quote, but never use a different line.
    matches=[]
    for sample_type in ("opening","current"):
        q=observed.get(sample_type) or {}
        if all(abs(float(q[k])-float(v))<0.001 for k,v in (
          ("line",quote["line"]),("first_side",quote["over"]),("second_side",quote["under"]))):
            matches.append(sample_type)
    checks["labeled_total_screenshot_correspondence"]=bool(matches)
    verified_home_away=all(checks[k] for k in (
      "basketball_first_field_is_home","basketball_second_field_is_away",
      "basketball_live_first_home","basketball_live_second_away",
      "html_first_price_home_column","html_second_price_away_column",
      "market_111_112_114_explicit"))
    return {
      "source":"ONLY_007_PUBLIC_JC_JS_AND_USER_LABELED_007_SCREENSHOT",
      "checks":checks,
      "reference_game_id":TEST_ID,
      "screenshot_quote":quote,
      "feed_quote_matches":matches,
      "home_away_orientation_verified":verified_home_away,
      "totals_over_under_orientation_verified":checks["labeled_total_screenshot_correspondence"],
      "market_slot_mapping":{
        "win_lose":{"first_side":"HOME_WIN" if verified_home_away else "UNVERIFIED",
                    "second_side":"AWAY_WIN" if verified_home_away else "UNVERIFIED"},
        "handicap":{"first_side":"HOME_HANDICAP_WIN" if verified_home_away else "UNVERIFIED",
                    "second_side":"AWAY_HANDICAP_WIN" if verified_home_away else "UNVERIFIED"},
        "total":{"first_side":"OVER" if checks["labeled_total_screenshot_correspondence"] else "UNVERIFIED",
                 "second_side":"UNDER" if checks["labeled_total_screenshot_correspondence"] else "UNVERIFIED"}
      },
      "official_ticketing_api_verified":False,
      "calibration_or_value_edge_verified":False
    }

def self_test():
    c=b"_glJC.jcOddsLq = function(infoStr) {this.homeWin_f = arr[1];this.guestWin_f = arr[2];this.homeWin = arr[indexNum];this.guestWin = arr[indexNum + 1];} 111 112 114"
    b=b"""html.push('<td class="H_Odd hlbg">' + homeWin + '</td>');html.push('<td class="G_Odd hlbg">' + guestWin + '</td>');"""
    raw=(b"728173^1.9^1.5^0^2.1^1.4^0$728173^1.7^1.7^2.5^1.75^1.65^3.5$728173^1.66^1.74^234.5^1.66^1.74^237.5")
    board={"requested_display_date":"2026-10-31","nba_cba_games":[{"game_id":"728173","league":"NBA","home_team":"金州勇士","away_team":"洛杉矶湖人"}]}
    screen={"rows":[{"match_no":"317","home":"勇士","away":"湖人","total":{"selection_order":"LABELED","line":234.5,"over":1.66,"under":1.74}}]}
    accepted=evidence(c,b,raw,board,screen)
    assert accepted["home_away_orientation_verified"]
    assert accepted["totals_over_under_orientation_verified"]
    assert accepted["feed_quote_matches"]==["opening"]
    inverted=json.loads(json.dumps(screen))
    inverted["rows"][0]["total"]["over"],inverted["rows"][0]["total"]["under"]=1.74,1.66
    assert not evidence(c,b,raw,board,inverted)["totals_over_under_orientation_verified"]
    print("JC_DIRECTION_SEMANTIC_EVIDENCE_SELF_TEST_PASS")

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--board")
    p.add_argument("--screenshot")
    p.add_argument("--output")
    p.add_argument("--self-test",action="store_true")
    a=p.parse_args()
    if a.self_test:return self_test()
    if not a.board or not a.screenshot:raise SystemExit("BOARD_AND_SCREENSHOT_REQUIRED")
    rp,status=robots_policy()
    if rp is False or (rp is not None and any(not rp.can_fetch(UA,ORIGIN+p) for p in (COMMON,BASKET,ODDS))):
        raise RuntimeError("PUBLIC_SOURCE_ACCESS_NOT_PERMITTED_"+status)
    args=[get_bytes(ORIGIN+p,240000 if p!=ODDS else 300000) for p in (COMMON,BASKET,ODDS)]
    out=evidence(*args,json.loads(Path(a.board).read_text(encoding="utf-8")),
      json.loads(Path(a.screenshot).read_text(encoding="utf-8")))
    if a.output:Path(a.output).write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("JC_DIRECTION_SEMANTIC_EVIDENCE",json.dumps(out,ensure_ascii=False))
if __name__=="__main__":main()
