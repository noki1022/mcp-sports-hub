#!/usr/bin/env python3
"""Admit verified, licensed, score-only historical NBA games (2007-08..2014-15).

Two-source strict score match: FiveThirtyEight NBA Elo paired NBA game rows
against Line Sheet score columns. No odds, Elo after game, or publisher forecasts
become training features. Downloads stay in memory; only an audited *eligible*
normalized dataset and small metadata may be written to a temporary directory.

The consumer MUST build as-of features by grouped date, never including own-day
scores; this data is historical labels, not contemporaneous quote snapshots.
"""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
from datetime import date, datetime
import csv
import hashlib
import io
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from nba_archive_crosscheck import LINE_SHEET, bounded_fetch, num
from sbr_archive_import import canonical_team

SOURCE="https://raw.githubusercontent.com/fivethirtyeight/data/master/nba-elo/nbaallelo.csv"
LICENSE="https://github.com/fivethirtyeight/data/blob/master/LICENSE"
START="2007-08-01"
END="2015-08-01"
TEAM_ALIAS={
    "BRK":"BKN","NJN":"BKN","CHO":"CHA","CHH":"CHA",
    "NOH":"NOP","NOK":"NOP","PHO":"PHX",
    "SEA":"SEA","OKC":"OKC","SA":"SAS"
}
ELO_REQUIRED={"game_id","lg_id","year_id","date_game","team_id","opp_id",
              "pts","opp_pts","game_location","game_result","is_playoffs"}

def team(x):
    x=str(x).strip().upper()
    if x in TEAM_ALIAS:return TEAM_ALIAS[x]
    allowed={"ATL","BOS","BKN","CHA","CHI","CLE","DAL","DEN","DET","GSW",
             "HOU","IND","LAC","LAL","MEM","MIA","MIL","MIN","NOP","NYK",
             "OKC","ORL","PHI","PHX","POR","SAC","SAS","TOR","UTA","WAS","SEA"}
    return x if x in allowed else None

def parse_date(s):
    # Typical FiveThirtyEight format is m/d/YYYY; exact date validation.
    return datetime.strptime(s.strip(),"%m/%d/%Y").date().isoformat()

def parse_score_reference(blob):
    """Reference score lookup is independent of dubious odds fields."""
    rd=csv.DictReader(io.StringIO(blob.decode("utf-8-sig")))
    required={"Date","Home","Away","Points","Win_Margin","home_win"}
    if not required.issubset(rd.fieldnames or []):raise ValueError("LINE_SHEET_SCORE_SCHEMA")
    keys=defaultdict(list)
    bad=Counter()
    for row in rd:
        try:
            day=date.fromisoformat(row["Date"].strip()).isoformat()
            if not START<=day<END:continue
            h,a=canonical_team(row["Home"]),canonical_team(row["Away"])
            if h is None or a is None or h==a:raise ValueError("UNMAPPED_REFERENCE_TEAM")
            total,margin=num(row["Points"]),num(row["Win_Margin"])
            if not (total.is_integer() and margin.is_integer() and (total+margin)%2==0):
                raise ValueError("INVALID_REFERENCE_SCORE_PARITY")
            hp,ap=int((total+margin)/2),int((total-margin)/2)
            if not (40<=hp<=200 and 40<=ap<=200):raise ValueError("INVALID_REFERENCE_SCORE")
            if int(num(row["home_win"]))!=int(hp>ap):raise ValueError("INVALID_REFERENCE_WINNER")
            keys[(day,h,a)].append((hp,ap))
        except (ValueError,KeyError,TypeError) as exc:
            bad[str(exc) if len(str(exc))<64 else "INVALID_REFERENCE"]+=1
    valid={}; duplicates=Counter()
    for k,vals in keys.items():
        if len(vals)==1: valid[k]=vals[0]
        elif len(set(vals))==1:
            valid[k]=vals[0];duplicates["identical_rows_ignored"]+=len(vals)-1
        else:duplicates["conflicting_key_excluded"]+=1
    return valid,{"valid_pairs":len(valid),"invalid":dict(bad),
                  "duplicates":dict(duplicates)}

def fivethirtyeight_games(blob):
    rd=csv.DictReader(io.StringIO(blob.decode("utf-8-sig")))
    if not ELO_REQUIRED.issubset(rd.fieldnames or []):
        raise ValueError("FIVETHIRTYEIGHT_SCHEMA_CHANGED")
    groups=defaultdict(list)
    stats=Counter()
    for r in rd:
        if r["lg_id"]!="NBA":continue
        try:
            d=parse_date(r["date_game"])
            if not START<=d<END:continue
            year=int(r["year_id"])
            if not 2008<=year<=2015:raise ValueError("SEASON_YEAR_MISMATCH")
        except (ValueError,TypeError) as exc:
            stats["invalid_date_or_season"]+=1;continue
        groups[r["game_id"]].append((d,r))
    accepted={}
    for game_id,pair in groups.items():
        if len(pair)!=2:
            stats["not_exactly_two_teams"]+=1;continue
        (d1,a),(d2,b)=pair
        if d1!=d2:
            stats["paired_date_mismatch"]+=1;continue
        sites=[str(a["game_location"]).strip(),str(b["game_location"]).strip()]
        if "N" in sites:
            stats["neutral_site_excluded"]+=1;continue
        if set(sites)!={"H","A"}:
            stats["home_away_not_reciprocal"]+=1;continue
        h,v=(a,b) if sites[0]=="H" else (b,a)
        home,away=team(h["team_id"]),team(v["team_id"])
        if not home or not away or home==away:
            stats["historical_team_unmapped"]+=1;continue
        if team(h["opp_id"])!=away or team(v["opp_id"])!=home:
            stats["opponent_id_mismatch"]+=1;continue
        try:
            hp,ap=int(h["pts"]),int(v["pts"])
            if any(int(x["pts"])!=float(x["pts"]) or int(x["opp_pts"])!=float(x["opp_pts"]) for x in (h,v)):
                raise ValueError("NON_INTEGER_POINTS")
            if not (40<=hp<=200 and 40<=ap<=200):
                raise ValueError("SCORE_OUT_OF_RANGE")
            if int(h["opp_pts"])!=ap or int(v["opp_pts"])!=hp:
                raise ValueError("RECIPROCAL_SCORE_CONFLICT")
            if hp==ap:
                raise ValueError("NBA_TIE_INVALID")
            if h["game_result"].strip() != ("W" if hp>ap else "L"):
                raise ValueError("HOME_WINNER_MISMATCH")
            if v["game_result"].strip() != ("W" if ap>hp else "L"):
                raise ValueError("AWAY_WINNER_MISMATCH")
            playoff=h["is_playoffs"].strip()
            if playoff!=v["is_playoffs"].strip() or playoff not in ("0","1"):
                raise ValueError("PLAYOFF_FLAG_MISMATCH")
        except (ValueError,TypeError,KeyError) as e:
            stats[str(e) if len(str(e))<70 else "BAD_SCORE"]+=1;continue
        key=(d1,home,away)
        if key in accepted:
            stats["duplicate_same_date_matchup_excluded"]+=1
            del accepted[key]
            continue
        accepted[key]={"date":d1,"home":home,"away":away,
                       "home_points":hp,"away_points":ap,
                       "playoffs":int(playoff)}
    return accepted,dict(stats)

def verify(elo_blob,ref_blob):
    games, rejected=fivethirtyeight_games(elo_blob)
    refs, ref_audit=parse_score_reference(ref_blob)
    accepted=[]; reasons=Counter(); years=Counter()
    for key,g in games.items():
        ref=refs.get(key)
        if not ref:
            reasons["NO_INDEPENDENT_SCORE_REFERENCE"]+=1;continue
        if ref!=(g["home_points"],g["away_points"]):
            reasons["INDEPENDENT_SCORE_CONFLICT"]+=1;continue
        # Game-by-game features must be generated STRICTLY from prior dates.
        # These are score/label-only rows, not prices or market predictors.
        accepted.append(g)
        years[g["date"][:4]]+=1
    accepted.sort(key=lambda r:(r["date"],r["home"],r["away"]))
    if len(accepted)!=len({(x["date"],x["home"],x["away"]) for x in accepted}):
        raise AssertionError("DUPLICATE_ADMITTED_KEY")
    if any("elo" in k.lower() or "forecast" in k.lower() or "odds" in k.lower()
           for g in accepted for k in g):
        raise AssertionError("FUTURE_OR_UNVERIFIED_MARKET_FIELD_LEAK")
    return accepted,{
        "source":"FiveThirtyEight Historical NBA Elo",
        "source_url":SOURCE,"license":"CC-BY-4.0","license_url":LICENSE,
        "source_sha256":hashlib.sha256(elo_blob).hexdigest(),
        "reference_source_url":LINE_SHEET,
        "reference_sha256":hashlib.sha256(ref_blob).hexdigest(),
        "reference_audit":ref_audit,
        "eligible_seasons":"2007-08 through 2014-15",
        "five_thirty_eight_matched_structure":len(games),
        "score_only_training_admitted":len(accepted),
        "source_rejections":rejected,"cross_reference_rejections":dict(reasons),
        "admitted_by_calendar_year":dict(sorted(years.items())),
        "pre_game_elo_or_post_game_features_included":False,
        "moneyline_spread_total_features_included":False,
        "historical_only_not_2025_26_test":True,
        "postdate_eligibility_rule":"all input games date < prediction date; process same-day games as a batch",
        "label_role":"train_candidate_score_only_era_shift_review",
        "do_not_promote_into_existing_2025_26_holdout":True,
    }

def self_test():
    # Two synthetic reciprocal 538 rows & independent-score record, plus
    # structural rejection check for neutral games.
    h={"game_id":"1","lg_id":"NBA","year_id":"2012","date_game":"11/1/2011",
       "team_id":"BOS","opp_id":"NYK","pts":"112","opp_pts":"100",
       "game_location":"H","game_result":"W","is_playoffs":"0"}
    a={**h,"team_id":"NYK","opp_id":"BOS","pts":"100","opp_pts":"112",
       "game_location":"A","game_result":"L"}
    fields=list(h)
    buf=io.StringIO();w=csv.DictWriter(buf,fields);w.writeheader();w.writerow(h);w.writerow(a)
    games,rej=fivethirtyeight_games(buf.getvalue().encode())
    assert len(games)==1 and not rej
    key=next(iter(games))
    assert key==("2011-11-01","BOS","NYK")
    a["opp_pts"]="111"
    buf=io.StringIO();w=csv.DictWriter(buf,fields);w.writeheader();w.writerow(h);w.writerow(a)
    games,rejected=fivethirtyeight_games(buf.getvalue().encode())
    assert not games and rejected["RECIPROCAL_SCORE_CONFLICT"]==1
    assert team("BRK")=="BKN" and team("NOH")=="NOP"
    print("NBA_538_STRICT_TRAINING_CANDIDATE_SELF_TEST_PASS")

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--self-test",action="store_true")
    p.add_argument("--out",type=Path)
    p.add_argument("--manifest",type=Path)
    args=p.parse_args()
    if args.self_test:return self_test()
    source=bounded_fetch(SOURCE,limit=25_000_000)
    reference=bounded_fetch(LINE_SHEET,limit=9_000_000)
    eligible,manifest=verify(source,reference)
    print("NBA_TRAINING_SOURCE_AUDIT "+json.dumps(manifest,ensure_ascii=False,sort_keys=True))
    if len(eligible)<6000 or manifest["cross_reference_rejections"].get("INDEPENDENT_SCORE_CONFLICT",0)>10:
        raise SystemExit("STRICT_TRAINING_SOURCE_INSUFFICIENT_OR_CONFLICT_RISK")
    if args.out:
        args.out.parent.mkdir(parents=True,exist_ok=True)
        with args.out.open("w",encoding="utf-8") as f:
            writer=csv.DictWriter(f,fieldnames=["date","home","away","home_points","away_points","playoffs"])
            writer.writeheader();writer.writerows(eligible)
    if args.manifest:
        args.manifest.parent.mkdir(parents=True,exist_ok=True)
        args.manifest.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
    print("NBA_TRAINING_SOURCE_ACCEPTED "+json.dumps({
        "score_only_games":len(eligible),"status":"SOURCE_ACCEPTED_SCORE_ONLY",
        "market_odds_training_admitted":0,"raw_archive_in_repo":False},sort_keys=True))

if __name__=="__main__":main()
