#!/usr/bin/env python3
"""Join all legitimate pretip odd sources: 007 archive + The Odds API.

Exact scores event_id, bookmaker updated time and source captured time required
for a priced match. Multiple bookmaker/market rows are not independent games.
No 007 price-side orientation may be silently reinterpreted; all 007 prices
remain raw until independent direction verification. Research only.
"""
from __future__ import annotations
import argparse,hashlib,json,sys
from collections import Counter,defaultdict
from datetime import datetime,timezone
from pathlib import Path

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
from historical_odds_validator import (read_snapshots,transform_history,dt)

MARKET_NAME={"h2h":"INDEPENDENT_BOOK_MONEYLINE",
             "spreads":"INDEPENDENT_BOOK_HANDICAP",
             "totals":"INDEPENDENT_BOOK_TOTAL"}


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))

def event_score_index(path):
    doc=read_json(path)
    byid={}
    conflicts=set()
    for g in doc.get("games",[]):
        gid=str(g.get("event_id") or "")
        if not gid or gid in conflicts: continue
        hp,ap=g.get("home_points"),g.get("away_points")
        try:
            score=(int(hp),int(ap))
        except (TypeError,ValueError):
            continue
        if (not g.get("completed") or score[0]<40 or score[1]<40 or
            not g.get("home_team") or not g.get("away_team")):
            continue
        if gid in byid:
            conflicts.add(gid)
            byid.pop(gid,None)
            continue
        byid[gid]={**g,"_score":score}
    return byid,conflicts

def oddsapi_rows(root):
    data_dir=Path(root)/"data/odds"
    outcomes,conflicts=event_score_index(Path(root)/"data/results/odds_api_scores.json")
    snapshots=[]
    audit=Counter()
    input_paths=[]
    for path in sorted(data_dir.glob("*the_odds_api.json")):
        raw=read_snapshots(str(path))
        snapshots.extend(raw)
        input_paths.append(str(path.relative_to(root)))
    parsed=transform_history(snapshots)
    row_list=[]
    seen={}
    invalid_keys=set()
    for r in parsed["rows"]:
        evt=r["event_id"]
        score=outcomes.get(evt)
        has_score=False
        actual_first=None
        if score is not None:
            tip=dt(r["commence_time_utc"])
            score_tip=dt(score.get("commence_time"))
            # Verified original provider team IDs are available through the
            # strict 30-team alias table; scores must agree with them exactly.
            from historical_odds_validator import team
            if (team(score["home_team"])==r["home"] and
                team(score["away_team"])==r["away"] and
                abs((tip-score_tip).total_seconds())<=3600):
                hp,ap=score["_score"]
                has_score=True
                if r["market"]=="h2h":
                    diff=hp-ap
                elif r["market"]=="spreads":
                    diff=hp-ap+r["home_handicap_point"]
                else:
                    diff=hp+ap-r["total_point"]
                actual_first="PUSH" if abs(diff)<1e-6 else "FIRST_SIDE" if diff>0 else "SECOND_SIDE"
            else:
                audit["SCORE_ID_HOME_AWAY_TIP_CONFLICT"]+=1

        out={
            "schema_version":"nba-combined-odds-asof-research-v1",
            "provider":"the-odds-api-v4",
            "game_key":"ODDSAPI:"+evt,
            "nba_event_id":evt,
            "beijing_date":(dt(r["commence_time_utc"]).astimezone(
                  __import__("datetime").timezone(__import__("datetime").timedelta(hours=8)))
                  .date().isoformat()),
            "tipoff_utc":r["commence_time_utc"],
            "source_quote_captured_utc":r["snapshot_time_utc"],
            "bookmaker_last_update_utc":r["price_last_update_utc"],
            "market":MARKET_NAME[r["market"]],
            "bookmaker":r["bookmaker"],
            "home_abbrev":r["home"],"away_abbrev":r["away"],
            "first_side":"home" if r["market"]!="totals" else "over",
            "second_side":"away" if r["market"]!="totals" else "under",
            "signed_home_handicap":r["home_handicap_point"],
            "total_line":r["total_point"],
            "price_first_decimal":r["first_price_decimal"],
            "price_second_decimal":r["second_price_decimal"],
            "price_first_no_vig":r["p_first_no_vig"],
            "price_second_no_vig":r["p_second_no_vig"],
            "line_and_price_orientation_verified":True,
            "pregame_quote_time_verified":True,
            "score_join_status":"EXACT_EVENT_TEAM_AND_TIP" if has_score else "NO_VERIFIED_FINAL",
            "settled_first_side":actual_first,
            "training_score_label_available":has_score,
            "source_note":"Archived and previously captured The Odds API; no new paid requests",
            "no_production_promotion":True,
        }
        identity=(out["game_key"],out["bookmaker"],out["market"],
                  out["source_quote_captured_utc"])
        if identity in invalid_keys:continue
        if identity in seen:
            if seen[identity] != out:
                invalid_keys.add(identity);seen.pop(identity,None)
                audit["CONFLICTING_ODDSAPI_SNAPSHOT_MARKET"]+=1
            else:
                audit["DUPLICATED_IDENTICAL_ODDSAPI_MARKET"]+=1
            continue
        seen[identity]=out
    row_list=sorted(seen.values(),key=lambda r:(
        r["tipoff_utc"],r["game_key"],r["bookmaker"],r["market"]))
    audit.update(parsed["audit"].get("rejections",{}))
    audit["input_snapshot_files"]=len(input_paths)
    audit["accepted_price_rows"]=len(row_list)
    audit["distinct_games"]=len({r["game_key"] for r in row_list})
    audit["priced_labeled_rows"]=sum(r["training_score_label_available"] for r in row_list)
    audit["priced_labeled_games"]=len({
        r["game_key"] for r in row_list if r["training_score_label_available"]})
    audit["unique_bookmakers"]=len({r["bookmaker"] for r in row_list})
    audit["completed_score_event_ids"]=len(outcomes)
    audit["duplicate_score_event_ids"]=len(conflicts)
    return row_list,dict(audit)

def combine(root,asof_path):
    import nba_007_historical_odds_backfill as seven
    quoted,cutoffs,seven_meta=seven.reconstruct(root)
    offered=[]
    for r in quoted:
        is_settled=r["settled_result"] is not None
        offered.append({
            "schema_version":"nba-combined-odds-asof-research-v1",
            "provider":"007",
            "game_key":"007:"+r["beijing_date"]+":"+r["game_id"],
            "nba_event_id":r["nba_game_id"],
            "beijing_date":r["beijing_date"],
            "tipoff_utc":r["tipoff_utc"],
            "source_quote_captured_utc":r["quote_capture_utc"],
            "bookmaker_last_update_utc":None,
            "market":r["market"],
            "bookmaker":r["bookmaker"],
            "signed_home_handicap":r["signed_home_handicap"],
            "total_line":r["line"] if r["market"].endswith("TOTAL") else None,
            "price_first_decimal":r["raw_slot1_price"] if r["price_units"]=="DECIMAL" else 1+r["raw_slot1_price"],
            "price_second_decimal":r["raw_slot2_price"] if r["price_units"]=="DECIMAL" else 1+r["raw_slot2_price"],
            "price_first_no_vig":None,
            "price_second_no_vig":None,
            "first_side":"RAW_SLOT_1_MAPPING_NOT_CERTIFIED",
            "second_side":"RAW_SLOT_2_MAPPING_NOT_CERTIFIED",
            "line_and_price_orientation_verified":False,
            "pregame_quote_time_verified":True,
            "score_join_status":"007_EXACT_GAME_AND_SETTLED" if is_settled else "NO_VERIFIED_FINAL",
            "settled_first_side":r["observed_first_side_result"] if is_settled else None,
            "training_score_label_available":is_settled,
            "source_note":"007 raw slot convention retained; no price-to-side probability certification",
            "source_file":r["source_archive_file"],
            "no_production_promotion":True
        })
    multi,api_stats=oddsapi_rows(root)
    all_rows=sorted(offered+multi,key=lambda r:(
        r["tipoff_utc"],r["game_key"],r["bookmaker"],r["market"],r["source_quote_captured_utc"]))
    meta={
       "schema_version":"nba-combined-odds-asof-research-v1",
       "coverage_by_provider":{
          "007": {"market_quote_rows":len(offered),
                  "distinct_games":len({r["game_key"] for r in offered}),
                  "labeled_quote_rows":sum(r["training_score_label_available"] for r in offered)},
          "the-odds-api-v4":api_stats,
       },
       "source_files_checked": "COMMITTED_REPO_ARCHIVES_ONLY",
       "all_market_quote_rows":len(all_rows),
       "unique_games_all_providers":len({r["game_key"] for r in all_rows}),
       "unique_labeled_games":len({r["game_key"] for r in all_rows
                                    if r["training_score_label_available"]}),
       "priced_direction_verified_labeled_rows":sum(
           r["training_score_label_available"] and r["line_and_price_orientation_verified"]
           for r in all_rows),
       "asof_price_source_not_a_random_train_test_split":True,
       "model_training_ready":"DATASET_ONLY_WAIT_INDEPENDENT_CHRONOLOGICAL_HOLDOUT",
       "production_promotion_allowed":False,
       "provider_ids":["007","the-odds-api-v4"],
    }
    return all_rows,meta

def run(root,out):
    rows,meta=combine(Path(root),None)
    dest=Path(out);dest.mkdir(parents=True,exist_ok=True)
    with (dest/"all_providers_pretip_odds.jsonl").open("w") as f:
        for r in rows:f.write(json.dumps(r,ensure_ascii=False,sort_keys=True)+"\n")
    dest.joinpath("manifest.json").write_text(json.dumps(meta,ensure_ascii=False,indent=2)+"\n")
    print("NBA_MULTI_PROVIDER_ODDS_ASOF_ADMITTED",json.dumps(meta,ensure_ascii=False))
    return meta

def self_test():
    from historical_odds_validator import team
    assert team("Los Angeles Lakers")=="LAL"
    assert dt("2026-10-29T12:00:00Z")<dt("2026-10-30T00:00:00Z")
    print("NBA_MULTI_PROVIDER_ODDS_ASOF_SELF_TEST_PASS")

if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("--repo-root",default=".")
    ap.add_argument("--out",default="/tmp/nba-multi-provider-asof")
    ap.add_argument("--self-test",action="store_true")
    args=ap.parse_args()
    if args.self_test:self_test()
    else:run(args.repo_root,args.out)
