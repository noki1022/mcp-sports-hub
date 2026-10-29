#!/usr/bin/env python3
"""Independent *route* game-score audit: FiveThirtyEight/Neil/Line Sheet vs NBA Stats Kaggle game index.

The Kaggle game index is used only as an IN-MEMORY VERIFIER; none of its data
is redistributed or used as a model feature. Upstream authorship independence
still requires documentary proof, so this audit cannot assert it.
"""
import csv,io,json,hashlib,sys
from collections import Counter,defaultdict
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
sys.path.insert(0,str(Path(__file__).resolve().parent))
import kaggle_nba_foundation_batches as kb
from nba_538_training_source import SOURCE,LINE_SHEET,bounded_fetch,verify as verify_old
from nba_2015_22_training_expansion import UPSTREAM,crossverify as verify_new,CODES
ALIASES={"BRK":"BKN","NJN":"BKN","NOH":"NOP","NOK":"NOP","CHO":"CHA","CHH":"CHA","PHO":"PHX","GS":"GSW","SA":"SAS","WSH":"WAS"}
def team(x):
    s=str(x).strip().upper()
    s=ALIASES.get(s,s)
    return s if s in CODES else None
def independent_game_index(blob):
    matches=defaultdict(set);reasons=Counter()
    rd=csv.DictReader(io.StringIO(blob.decode("utf-8-sig")))
    needed={"game_id","game_date","home","away","pts_home","pts_away"}
    if not needed.issubset(rd.fieldnames or []):raise RuntimeError("INDEX_SCHEMA_CHANGED")
    for r in rd:
        try:
            day=r["game_date"][:10]
            if not "2007-08-01"<=day<"2022-08-01":continue
            h,a=team(r["home"]),team(r["away"])
            if h is None or a is None or h==a:raise ValueError("TEAM_UNMAPPED")
            hp,ap=int(float(r["pts_home"])),int(float(r["pts_away"]))
            if hp==ap or not 40<=hp<=200 or not 40<=ap<=200:raise ValueError("BAD_SCORE")
            matches[(day,h,a)].add((hp,ap))
        except (ValueError,KeyError,TypeError) as e:
            reasons[str(e)[:70]]+=1
    valid={k:next(iter(v)) for k,v in matches.items() if len(v)==1}
    reasons["index_conflicting_duplicate_keys"]=sum(len(v)>1 for v in matches.values())
    return valid,reasons
def run():
    source538=bounded_fetch(SOURCE,limit=25_000_000)
    neil=bounded_fetch(UPSTREAM,limit=22_000_000)
    line=bounded_fetch(LINE_SHEET,limit=9_000_000)
    original,audit_538=verify_old(source538,line)
    expanded,audit_neil=verify_new(neil,line)
    archive,members=kb.archive_entries()
    raw=kb.fetch_member(archive,members["csv/games_index.csv"])
    third,diag=independent_game_index(raw)
    rows=original+expanded
    family=Counter();matched={};conflict=[];missing=Counter()
    for row in rows:
        key=(row["date"],row["home"],row["away"])
        origin="fivethirtyeight" if row["date"]<"2015-08-01" else "neil_paine"
        ver=third.get(key)
        family[origin+"_input"]+=1
        if ver is None:missing[origin]+=1;continue
        if ver!=(row["home_points"],row["away_points"]):
            conflict.append({"season":row["date"][:4],"family":origin})
            family[origin+"_score_conflict"]+=1
            continue
        family[origin+"_score_matched"]+=1
        matched[key]=row
    report={"score_sources":{"fivethirtyeight":SOURCE,"neil_paine":UPSTREAM,
                              "reference_one":LINE_SHEET,"reference_two":"https://www.kaggle.com/datasets/chevronronson/nba-stats-dataset"},
      "scores_source_hashes":{"538":hashlib.sha256(source538).hexdigest(),"neil":hashlib.sha256(neil).hexdigest(),
                              "linesheet":hashlib.sha256(line).hexdigest(),"kaggle_game_index":hashlib.sha256(raw).hexdigest()},
      "source_index_rows":len(third),"source_index_parse_rejections":dict(diag),
      "crosscheck":dict(family),"no_reference_match":dict(missing),
      "conflict_count":len(conflict),"matched_games":len(matched),
      "training_promoted":0,"external_upstream_documented_independent":False,
      "zip_bytes_read":kb.remote.spent,"any_verifier_rows_stored":False}
    print("NBA_INDEPENDENT_ROUTE_SCORE_AUDIT "+json.dumps(report,sort_keys=True),flush=True)
    if len(matched)<15000:raise SystemExit("THIRD_SOURCE_OVERLAP_TOO_LOW")
    if len(conflict)>25:raise SystemExit("TOO_MANY_THIRD_SOURCE_SCORE_CONFLICTS")
def test():
    assert team("PHO")=="PHX"
    assert team("NJN")=="BKN"
    raw=b"game_id,game_date,home,away,pts_home,pts_away\n1,2018-11-01T00:00:00,BOS,NYK,110,100\n2,2018-11-02T00:00:00,BOS,NYK,110,99\n"
    refs,_=independent_game_index(raw)
    assert len(refs)==2
    print("NBA_THIRD_ROUTE_CROSSCHECK_SELF_TEST_PASS")
if __name__=="__main__":
    if "--self-test" in sys.argv:test()
    else:run()
