#!/usr/bin/env python3
"""Source-audited 007 bookmaker-vs-theoretical Asian handicap diagnostics.

Do not average alternate lines as extra independent companies.
Do not compare Hong Kong net water across DIFFERENT handicap lines.
No real company quote is ever invented from European odds.
Not a live match prediction, EV or model promotion mechanism.
"""
from __future__ import annotations
import argparse
from collections import Counter,defaultdict
import hashlib,json,statistics
from pathlib import Path

VERSION="football-007-multi-company-asian-compare-v1"

def identity_sha(snapshot):
    return hashlib.sha256(json.dumps(snapshot,ensure_ascii=False,sort_keys=True).encode()).hexdigest()

def compare(snapshot,conversion):
    if snapshot.get("schema_version")!="football-jc-007-v1":
        raise ValueError("INVALID_FOOTBALL_SNAPSHOT")
    if conversion.get("source_snapshot_sha256")!=identity_sha(snapshot):
        raise ValueError("EURO_ASIAN_CONVERSION_NOT_FROM_SAME_SNAPSHOT")
    by_id={str(x["match_id"]):x for x in conversion.get("games",[])}
    result=[]
    counts=Counter()
    for game in snapshot.get("games",[]):
        mid=str(game["match_id"])
        src=game.get("asian_007")
        if not isinstance(src,dict) or game.get("asian_007_status")!="VERIFIED_MATCH_ID_TIME_AND_COMPANY_SCHEMA":
            counts["missing_asian_market"]+=1
            result.append({"match_id":mid,"jc_number":game.get("jc_number"),
                           "state":"007_ASIAN_QUOTES_NOT_VERIFIED",
                           "source_error":game.get("asian_007_status","NOT_CAPTURED")})
            continue
        if src.get("match_id")!=mid or src.get("schema_version")!="football-007-asian-multi-company-v1":
            raise ValueError("MISMATCHED_007_ASIAN_SOURCE_ID")
        expected=by_id.get(mid) or {}
        euro=expected.get("european_to_asian")
        theoretical={
            round(float(line["home_handicap"]),2):line
            for line in (euro or {}).get("asian_handicap_lines",[])
        }
        groups=defaultdict(list)
        companies=[]
        for c in src.get("companies",[]):
            main=c["main"]
            opening=main["initial_quote"]
            current=main["latest_quote"]
            ln=round(float(current["signed_home_asian_handicap"]),2)
            firstln=round(float(opening["signed_home_asian_handicap"]),2)
            home_hk=float(current["home_water"]["hong_kong_net"])
            away_hk=float(current["away_water"]["hong_kong_net"])
            theo=theoretical.get(ln)
            entry={"company_id":c["company_id"],
                   "company_name_cn":c["name_cn"],
                   "company_name_en":c["name_en"],
                   "primary_line_signed_home":ln,
                   "initial_line_signed_home":firstln,
                   "source_initial_time_unavailable":True,
                   "observed_current_modified_at_utc":current["modified_at_utc"],
                   "observed_current_home_hk_net":home_hk,
                   "observed_current_away_hk_net":away_hk,
                   "observed_current_home_decimal":round(1+home_hk,5),
                   "observed_current_away_decimal":round(1+away_hk,5),
                   "alternate_line_count":len(c["alternate_lines"]),
                   "line_changed_from_source_initial":ln!=firstln,
                   "home_water_change_hk_net_if_same_line":(
                       round(home_hk-float(opening["home_water"]["hong_kong_net"]),5)
                       if ln==firstln else None),
                   "away_water_change_hk_net_if_same_line":(
                       round(away_hk-float(opening["away_water"]["hong_kong_net"]),5)
                       if ln==firstln else None),
                   "model_implied_fair_price_available":theo is not None,
                   "model_vs_observed_home_price_difference_decimal":(
                       round(1+home_hk-float(theo["home_fair_decimal"]),5)
                       if theo is not None else None),
                   "model_vs_observed_away_price_difference_decimal":(
                       round(1+away_hk-float(theo["away_fair_decimal"]),5)
                       if theo is not None else None),
                   "not_a_betting_edge":True,
            }
            companies.append(entry)
            groups[ln].append(entry)
        if not companies:
            counts["zero_parsed_bookmakers"]+=1
            result.append({"match_id":mid,"jc_number":game.get("jc_number"),
                           "state":"ZERO_VALID_ASIAN_COMPANIES"})
            continue
        lines=[r["primary_line_signed_home"] for r in companies]
        consensus=[]
        for ln, items in sorted(groups.items()):
            consensus.append({
                "home_signed_asian_line":ln,
                "company_count":len(items),
                "median_home_hk_net":round(statistics.median(x["observed_current_home_hk_net"] for x in items),5),
                "median_away_hk_net":round(statistics.median(x["observed_current_away_hk_net"] for x in items),5),
                "company_ids":[x["company_id"] for x in items]})
        main_line,main_count=Counter(lines).most_common(1)[0]
        theoretical_line=(euro or {}).get("reference_balanced_asian_line")
        flags=[]
        if max(lines)-min(lines)>=.5:
            flags.append("BOOKMAKER_MAIN_LINE_DISPERSION_AT_LEAST_HALF_GOAL")
        if sum(x["line_changed_from_source_initial"] for x in companies)>=max(2,len(companies)//2):
            flags.append("MANY_BOOKMAKERS_MOVED_HANDICAP_LINE")
        if theoretical_line is None:
            flags.append("THEORETICAL_ASIAN_REFERENCE_UNAVAILABLE")
        if theoretical_line is not None and abs(main_line-theoretical_line)>=.5:
            flags.append("REAL_MARKET_MODE_VS_MODEL_THEORETICAL_LINE_DIFFERS_0_5_OR_MORE")
        counts["verified_asian_games"]+=1
        counts["verified_bookmaker_main_lines"]+=len(companies)
        result.append({"match_id":mid,"jc_number":game.get("jc_number"),
                       "state":"007_REAL_MULTI_COMPANY_ASIAN_RESEARCH",
                       "source_url":src["source_url"],
                       "source_sha256":src["sha256"],
                       "captured_at_utc":src["captured_at_utc"],
                       "company_count":len(companies),
                       "alternate_lines_excluded_from_company_consensus":
                           sum(x["alternate_line_count"] for x in companies),
                       "observed_main_line_mode_signed_home":main_line,
                       "mode_company_count":main_count,
                       "observed_main_line_median_signed_home":statistics.median(lines),
                       "model_reference_balanced_line_signed_home":theoretical_line,
                       "line_group_consensus":consensus,
                       "flags":flags,
                       "bookmakers":companies,
                       "interpretation":"MARKET_STRUCTURE_DIAGNOSTIC_NOT_PREDICTIVE_SIGNAL",
                       "source_times_not_asserted_synchronous":True})
    return {"version":VERSION,"source":"TITAN007_PUBLIC_ASIAN_MULTICOMPANY",
            "source_snapshot_sha256":identity_sha(snapshot),
            "game_count":len(result),"counts":dict(counts),
            "games":result,"no_basketball_dependency":True,"no_pushplus":True,
            "no_auto_model_probability_override":True,
            "no_claim_of_proven_predictive_gain":True,
            "market_scope":"ASIAN_TWO_WAY_PRICE_DIAGNOSTICS_FOR_FOOTBALL_JC_RESEARCH"}

def cli():
    p=argparse.ArgumentParser()
    p.add_argument("--snapshot",required=True)
    p.add_argument("--theoretical",required=True)
    p.add_argument("--out",required=True)
    args=p.parse_args()
    def load(path):
        raw=Path(path).read_bytes()
        if len(raw)>20_000_000:raise ValueError("OVERSIZED_007_RESEARCH_INPUT")
        return json.loads(raw)
    report=compare(load(args.snapshot),load(args.theoretical))
    target=Path(args.out);target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n","utf-8")
    print("FOOTBALL_007_ASIAN_REAL_VS_THEORY",json.dumps(report["counts"],ensure_ascii=False),
          "no model override no push")
if __name__=="__main__":cli()
