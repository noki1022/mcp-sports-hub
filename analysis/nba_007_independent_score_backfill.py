#!/usr/bin/env python3
"""Research-only: join archived, truly pre-tip 007 quotes to independent ESPN final scores.

ESPN may provide postgame labels, NEVER retrospective odds or missing timestamps.
Original 007 quote time, company ID3=Crown and raw side orientation are preserved.
"""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path

import nba_007_historical_odds_backfill as seven
from nba_multibook_asof_settled_ledger import fetch_espn_day, parse_espn
from titan007_ev_analysis import NAMES

SCHEMA = "nba-007-independent-final-label-v1"
MAX_DAYS = 10
ALIASES = {"GS": "GSW", "SA": "SAS", "NY": "NYK", "NO": "NOP", "UTAH": "UTA", "WSH": "WAS"}

def code(value):
    value = str(value or "").upper()
    return ALIASES.get(value, value)

def truth(row, score):
    if str(row["nba_game_id"]) != str(score["espn_event_id"]):
        return "EVENT_ID_CONFLICT"
    tip = seven.when(row["tipoff_utc"])
    actual_tip = seven.when(score["score_tip_utc"])
    if tip is None or actual_tip is None or abs((tip-actual_tip).total_seconds()) > 10800:
        return "TIPOFF_DISAGREEMENT"
    home, away = NAMES.get(row["home_team"]), NAMES.get(row["away_team"])
    if not home or not away:
        return "UNKNOWN_007_TEAM_ALIAS"
    if (code(home[0]), code(away[0])) != (code(score["home"]), code(score["away"])):
        return "HOME_AWAY_DISAGREEMENT"
    return None

def join(original, scores):
    """Pure auditable score-label enrichment; no new odds, zero model fitting."""
    candidates, conflict_ids = {}, set()
    for s in scores:
        event_id = str(s["espn_event_id"])
        identity = (s["home"], s["away"], s["score_tip_utc"],
                    s["home_points"], s["away_points"])
        if event_id in candidates:
            old = candidates[event_id]
            if identity != (old["home"],old["away"],old["score_tip_utc"],
                            old["home_points"],old["away_points"]):
                conflict_ids.add(event_id)
        else:
            candidates[event_id] = s
    for event_id in conflict_ids:
        candidates.pop(event_id, None)
    fixture_identity, invalid_games = {}, set()
    for r in original:
        key = (r["beijing_date"],r["game_id"])
        identity = (r["nba_game_id"],r["home_team"],r["away_team"],r["tipoff_utc"])
        if key in fixture_identity and fixture_identity[key] != identity:
            invalid_games.add(key)
        fixture_identity[key] = identity
    out, errors, newly = [], Counter(), set()
    prior_games = {(r["beijing_date"],r["game_id"]) for r in original
                   if r["settled_result"] is not None}
    for r in original:
        item = dict(r)
        game_key = (r["beijing_date"],r["game_id"])
        item["schema_version"] = SCHEMA
        item["score_backfill_status"] = "NO_INDEPENDENT_COMPLETED_SCORE"
        item["postgame_score_source"] = None
        item["new_score_label"] = False
        s = candidates.get(str(r["nba_game_id"]))
        error = ("MUTATED_ORIGINAL_IDENTITY" if game_key in invalid_games
                 else truth(r,s) if s is not None else None)
        if error:
            errors[error] += 1
            item["score_backfill_status"] = error
        elif s is not None:
            result = {"home_points":s["home_points"], "away_points":s["away_points"],
                      "margin":s["home_points"]-s["away_points"],
                      "total":s["home_points"]+s["away_points"]}
            old = r["settled_result"]
            if old is not None and (old["home_points"],old["away_points"]) != (
                    result["home_points"],result["away_points"]):
                errors["EXISTING_SCORE_CONFLICT_QUARANTINED"] += 1
                item["settled_result"] = None
                item["observed_first_side_result"] = None
                item["score_backfill_status"] = "SCORE_CONFLICT_QUARANTINED"
            else:
                if old is None:
                    item["settled_result"] = result
                    item["observed_first_side_result"] = seven.first_side_result(
                        r["market"],r["line"],result)
                    item["new_score_label"] = True
                    newly.add(game_key)
                item["score_backfill_status"] = "ESPN_EVENT_TEAMS_TIP_VERIFIED"
                item["postgame_score_source"] = {
                    "source":s["score_source"],
                    "source_url":s.get("score_source_url"),
                    "retrieved_utc":s["score_collected_utc"]}
        item["training_score_label_available"] = item["settled_result"] is not None
        item["price_side_probability_verified"] = False
        item["production_fusion_eligible"] = False
        out.append(item)
    games = {(r["beijing_date"],r["game_id"]) for r in out}
    labeled = {(r["beijing_date"],r["game_id"]) for r in out
               if r["training_score_label_available"]}
    return out, {
        "schema_version":SCHEMA,
        "original_quote_rows":len(original),
        "output_quote_rows":len(out),
        "distinct_games":len(games),
        "original_labeled_games":len(prior_games),
        "newly_labeled_games":len(newly),
        "labeled_games_after":len(labeled),
        "unlabeled_games_after":len(games-labeled),
        "newly_labeled_quote_rows":sum(r["new_score_label"] for r in out),
        "rejection_counts":dict(sorted(errors.items())),
        "same_game_quotes_not_independent":True,
        "source_capture_timestamps_unchanged":True,
        "original_bookmaker_update_time_not_inferred":True,
        "007_raw_price_side_unverified":True,
        "007_crown_id3_preserved":True,
        "production_promotion_allowed":False,
        "production_changed":False}

def run(repo, destination, provider=fetch_espn_day):
    quotes, _, prior = seven.reconstruct(Path(repo))
    missing = [r for r in quotes if r["settled_result"] is None]
    dates = sorted({d for r in missing for d in (
        seven.when(r["tipoff_utc"]).date(),
        (seven.when(r["tipoff_utc"])-timedelta(days=1)).date())})
    if len(dates)>MAX_DAYS:
        raise RuntimeError("BOUNDED_ESPN_FETCH_DAYS_EXCEEDED")
    outcomes, sources, failures = [], [], []
    now = datetime.now(timezone.utc)
    for d in dates:
        try:
            url, data, digest = provider(d)
            rows, rejected = parse_espn(data,url,now.isoformat().replace("+00:00","Z"))
            outcomes.extend(rows)
            sources.append({"date":d.isoformat(),"url":url,"sha256":digest,
                            "parsed_final_scores":len(rows),"rejections":dict(rejected)})
        except (OSError, ValueError, TypeError, TimeoutError, KeyError) as exc:
            failures.append({"date":d.isoformat(),"error":type(exc).__name__})
    labels, audit = join(quotes,outcomes)
    audit["scoreboard_sources"] = sources
    audit["scoreboard_fetch_failures"] = failures
    audit["baseline_observation_games"] = prior["observation_games"]
    output = Path(destination)
    output.mkdir(parents=True,exist_ok=True)
    ledger = output/"007_real_pretip_quotes_with_independent_final_scores.jsonl"
    ledger.write_text("".join(json.dumps(x,ensure_ascii=False,sort_keys=True)+"\n"
                              for x in labels),encoding="utf-8")
    audit["output_sha256"] = sha256(ledger.read_bytes()).hexdigest()
    (output/"audit.json").write_text(json.dumps(audit,ensure_ascii=False,indent=2,
                                               sort_keys=True)+"\n",encoding="utf-8")
    print("NBA_007_INDEPENDENT_SCORE_BACKFILL",json.dumps(audit,ensure_ascii=False))
    return audit

def selftest():
    row = {"beijing_date":"2026-11-01","game_id":"728880","nba_game_id":"401909896",
           "home_team":"犹他爵士","away_team":"波特兰开拓者",
           "tipoff_utc":"2026-10-31T19:00:00Z",
           "quote_capture_utc":"2026-10-31T17:00:00Z",
           "market":"CROWN_HANDICAP","line":-7.5,"settled_result":None,
           "observed_first_side_result":None,"price_side_probability_verified":False}
    score = {"espn_event_id":"401909896","home":"UTA","away":"POR",
             "score_tip_utc":"2026-10-31T19:00:00Z",
             "home_points":90,"away_points":112,"score_source":"ESPN_COMPLETED_GAME_SCOREBOARD",
             "score_source_url":"https://example.invalid/test",
             "score_collected_utc":"2026-11-02T00:00:00Z"}
    rows, meta = join([row],[score])
    assert meta["newly_labeled_games"]==1
    assert rows[0]["observed_first_side_result"]=="SECOND_SIDE"
    assert rows[0]["quote_capture_utc"]==row["quote_capture_utc"]
    assert not rows[0]["price_side_probability_verified"]
    bad, badmeta = join([row],[{**score,"away":"BOS"}])
    assert bad[0]["settled_result"] is None and badmeta["newly_labeled_games"]==0
    conflict = {**row,"settled_result":{"home_points":100,"away_points":99,
                                        "margin":1,"total":199}}
    quarantined, meta2 = join([conflict],[score])
    assert quarantined[0]["settled_result"] is None
    assert meta2["rejection_counts"]["EXISTING_SCORE_CONFLICT_QUARANTINED"]==1
    unresolved,_ = join([row],[])
    assert unresolved[0]["settled_result"] is None
    print("NBA_007_INDEPENDENT_SCORE_BACKFILL_SELFTEST_PASS")

if __name__=="__main__":
    a=argparse.ArgumentParser()
    a.add_argument("--repo-root",default=".")
    a.add_argument("--out",default="/tmp/nba-007-independent-score-backfill")
    a.add_argument("--selftest",action="store_true")
    args=a.parse_args()
    selftest() if args.selftest else run(args.repo_root,args.out)
