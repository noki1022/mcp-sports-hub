#!/usr/bin/env python3
"""Independent 007 football Jingcai forecast: HAD, HHAD and TTG only.

All inputs are captured PRE-KICKOFF, in an explicit snapshot. This is a
research baseline, NOT a trained/calibrated profitable betting model.
Never infer official JC handicap or unavailable market prices.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

VERSION = "football-jc-poisson-research-v1"
MARKETS = ("had", "hhad", "ttg")
HAD = ("主胜", "平", "客胜")
HHAD = ("让胜", "让平", "让负")
TTG = ("0球", "1球", "2球", "3球", "4球", "5球", "6球", "7+球")


def when(value):
    if not isinstance(value, str):
        raise ValueError("MISSING_SOURCE_TIMESTAMP")
    d = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if d.tzinfo is None:
        raise ValueError("TIMEZONE_REQUIRED")
    return d.astimezone(timezone.utc)


def number(value, low, high):
    if isinstance(value, bool):
        raise ValueError("BOOLEAN_NOT_A_NUMBER")
    x = float(value)
    if not math.isfinite(x) or not low <= x <= high:
        raise ValueError("NUMERIC_VALUE_OUT_OF_RANGE")
    return x


def source_url(url):
    if not isinstance(url, str):
        raise ValueError("007_SOURCE_URL_REQUIRED")
    u = urlparse(url)
    host = (u.hostname or "").lower()
    if u.scheme != "https" or not (host == "titan007.com" or host.endswith(".titan007.com")):
        raise ValueError("SOURCE_IS_NOT_007")
    return url


def validate_history(history, before, kind):
    if not isinstance(history, list) or len(history) > 10:
        raise ValueError("INVALID_" + kind)
    seen = set()
    rows = []
    for item in history:
        dt = when(item["played_at"])
        if dt >= before:
            raise ValueError("FUTURE_" + kind)
        identity = str(item.get("match_id") or "")
        if identity:
            if identity in seen:
                raise ValueError("DUPLICATE_" + kind)
            seen.add(identity)
        if kind == "H2H":
            gf = number(item["home_goals"], 0, 30)
            ga = number(item["away_goals"], 0, 30)
        else:
            gf = number(item["goals_for"], 0, 30)
            ga = number(item["goals_against"], 0, 30)
            venue = item.get("venue")
            if venue not in ("HOME", "AWAY"):
                raise ValueError("INVALID_RECENT_VENUE")
        rows.append((dt, gf, ga, item))
    rows.sort(key=lambda r: r[0], reverse=True)
    return rows


def weighted(rows, index, captured):
    if not rows:
        return None
    values = []
    for rank, (played, gf, ga, _) in enumerate(rows):
        days = max(0.0, (captured - played).total_seconds() / 86400)
        w = math.exp(-days / 100.0) * (0.90 ** rank)
        values.append((w, gf if index == 0 else ga))
    denom = sum(w for w, _ in values)
    return sum(w * v for w, v in values) / denom if denom > 1e-12 else None


def injury_effect(items, captured, kickoff):
    if not isinstance(items, list):
        raise ValueError("INVALID_INJURY_LIST")
    modifiers = {"home_attack": 0.0, "away_attack": 0.0,
                 "home_conceded": 0.0, "away_conceded": 0.0}
    seen = set()
    for item in items:
        observed = when(item["observed_at"])
        if observed > captured or observed >= kickoff:
            raise ValueError("POST_CAPTURE_INJURY_LEAK")
        team = item["team"]
        role = item["role"]
        state = item["status"]
        if team not in ("home", "away") or role not in ("GK", "DEF", "MID", "FWD"):
            raise ValueError("INVALID_INJURY_IDENTITY")
        if state not in ("OUT", "DOUBTFUL", "QUESTIONABLE", "AVAILABLE"):
            raise ValueError("INVALID_INJURY_STATUS")
        person = str(item.get("player_id") or item.get("player") or "").strip()
        if not person or (team, person) in seen:
            raise ValueError("MISSING_OR_DUPLICATE_PLAYER")
        seen.add((team, person))
        exposure = number(item["expected_minutes_share"], 0, 1)
        absence = {"OUT": 1.0, "DOUBTFUL": 0.75,
                   "QUESTIONABLE": 0.35, "AVAILABLE": 0.0}[state]
        # Untrained bounded heuristic. Only verified, timestamped player
        # information is allowed to alter goal expectation.
        if role in ("MID", "FWD"):
            modifiers[team + "_attack"] -= (0.10 if role == "MID" else 0.18) * exposure * absence
        else:
            modifiers[team + "_conceded"] += (0.16 if role == "GK" else 0.11) * exposure * absence
    return {k: max(-0.4, min(0.4, v)) for k, v in modifiers.items()}


def poisson(lam, maximum=18):
    p = [math.exp(-lam)]
    for k in range(1, maximum + 1):
        p.append(p[-1] * lam / k)
    p[-1] += max(0.0, 1.0 - sum(p))
    return p


def distribution(home_lam, away_lam, handicap):
    ph, pa = poisson(home_lam), poisson(away_lam)
    had = [0.0] * 3
    hhad = [0.0] * 3 if handicap is not None else None
    ttg = [0.0] * 8
    scores = []
    for h, a in enumerate(ph):
        for g, b in enumerate(pa):
            p = a * b
            had[0 if h > g else 1 if h == g else 2] += p
            if hhad is not None:
                adjusted = h + handicap - g
                hhad[0 if adjusted > 0 else 1 if adjusted == 0 else 2] += p
            ttg[min(7, h + g)] += p
            scores.append((p, h, g))
    scores.sort(reverse=True)
    return had, hhad, ttg, scores[0][1:]


def fair_market(odds, size):
    if odds is None:
        return None
    if not isinstance(odds, list) or len(odds) != size:
        raise ValueError("INVALID_JC_ODDS_COUNT")
    implied = [1.0 / number(x, 1.001, 1000) for x in odds]
    total = sum(implied)
    if total <= 0:
        raise ValueError("ZERO_MARKET_PROBABILITY")
    return [x / total for x in implied]


def market_result(labels, probs, odds):
    if probs is None:
        return {"status": "UNAVAILABLE_OFFICIAL_HANDICAP_NOT_VERIFIED",
                "probabilities": None, "direction": None}
    q = fair_market(odds, len(labels))
    ix = max(range(len(probs)), key=lambda i: probs[i])
    return {"status": "RESEARCH_UNCALIBRATED" if q is not None else "RESEARCH_ODDS_MISSING",
            "probabilities": {label: round(p, 6) for label, p in zip(labels, probs)},
            "direction": labels[ix], "direction_probability": round(probs[ix], 6),
            "jc_odds": odds, "jc_devig_probability": None if q is None else {
                label: round(p, 6) for label, p in zip(labels, q)},
            "probability_gap_pp": None if q is None else round(100 * (probs[ix] - q[ix]), 2)}


def build_match(game, captured):
    mid = str(game.get("match_id") or "").strip()
    kickoff = when(game["kickoff_beijing"])
    base = {"match_id": mid, "jc_number": game.get("jc_number"),
            "league": game.get("league"), "home_team": game.get("home_team"),
            "away_team": game.get("away_team"), "kickoff_beijing": game["kickoff_beijing"],
            "data_quality": {}, "markets": {}}
    if not mid or not all(isinstance(base[k], str) and base[k].strip()
                          for k in ("league", "home_team", "away_team")):
        raise ValueError("MISSING_FIXTURE_IDENTITY")
    source_url(game["source_url"])
    if kickoff <= captured:
        base.update(status="REJECTED_NOT_PREMATCH", reason="CAPTURE_AT_OR_AFTER_KICKOFF")
        return base
    asof = captured
    for field in ("form_observed_at", "h2h_observed_at", "injury_observed_at", "odds_observed_at"):
        if game.get(field) and when(game[field]) > asof:
            raise ValueError("POST_CAPTURE_FEATURE_" + field)
    home = validate_history(game.get("home_last5", []), asof, "HOME_FORM")[:5]
    away = validate_history(game.get("away_last5", []), asof, "AWAY_FORM")[:5]
    h2h = validate_history(game.get("h2h", []), asof, "H2H")[:5]
    injury_state = game.get("injury_report_state", "UNVERIFIED")
    if injury_state not in ("VERIFIED", "UNVERIFIED", "UNAVAILABLE"):
        raise ValueError("INVALID_INJURY_REPORT_STATE")
    reported_injuries = game.get("injuries", [])
    if injury_state != "VERIFIED" and reported_injuries:
        raise ValueError("UNVERIFIED_INJURIES_CANNOT_CHANGE_PROBABILITIES")
    injuries = injury_effect(reported_injuries, captured, kickoff)
    base["data_quality"] = {
        "home_recent": len(home), "away_recent": len(away), "h2h": len(h2h),
        "injury_state": injury_state,
        "injury_players": len(game.get("injuries", [])),
        "injury_listed_players_unconfirmed": len(game.get("injury_source_facts", [])),
        "analysis_source_status": game.get("analysis_source_status", "NOT_PROVIDED"),
        "source_evidence": ("LIVE_007_ANALYSIS_MATCH_ID_SHA_VERIFIED" if game.get("analysis_source_status") == "007_EMBEDDED_JSON_VALIDATED" else "007_URL_DECLARED_NOT_INDEPENDENTLY_ATTESTED"),
        "data_gaps": game.get("data_gaps", []),
        "baseline": "UNTRAINED_HEURISTIC_UNCALIBRATED"}
    if not game.get("jc_number"):
        base["data_quality"]["jc_number"] = "MISSING_DO_NOT_INVENT"
    markets = game.get("jc_markets") or {}
    if not isinstance(markets, dict):
        raise ValueError("INVALID_JC_MARKETS")
    had_odds = markets.get("had")
    ttg_odds = markets.get("ttg")
    hhad_raw = markets.get("hhad")
    handicap, hhad_odds = None, None
    if hhad_raw is not None:
        if not isinstance(hhad_raw, dict):
            raise ValueError("INVALID_HHAD_MARKET")
        handicap_value = number(hhad_raw["signed_home_handicap"], -12, 12)
        if not handicap_value.is_integer():
            raise ValueError("JC_HHAD_MUST_BE_INTEGER_GOALS")
        handicap = int(handicap_value)
        hhad_odds = hhad_raw.get("odds")
    if len(home) < 3 or len(away) < 3:
        base.update(status="INSUFFICIENT_FORM", reason="NEED_AT_LEAST_THREE_AUTHENTIC_PREGAME_RESULTS_PER_TEAM")
        for key in MARKETS:
            known_odds = {"had": had_odds, "hhad": hhad_odds, "ttg": ttg_odds}[key]
            base["markets"][key] = {"status": "UNAVAILABLE_FORM_INSUFFICIENT",
                                    "direction": None, "probabilities": None,
                                    "jc_odds": known_odds}
            if key == "hhad":
                base["markets"][key]["signed_home_handicap"] = handicap
        return base
    # Transparent low-complexity research model, not a claim of trained Elo/xG.
    # Geometric mean of attacking and opposing defense strength, with an
    # explicit prior smoothing. Both sides' recent form feed the same score grid.
    home_gf, home_ga = weighted(home, 0, captured), weighted(home, 1, captured)
    away_gf, away_ga = weighted(away, 0, captured), weighted(away, 1, captured)
    home_lambda = 0.35 * 1.40 + 0.65 * math.sqrt(max(0.10, home_gf) * max(0.10, away_ga))
    away_lambda = 0.35 * 1.15 + 0.65 * math.sqrt(max(0.10, away_gf) * max(0.10, home_ga))
    if h2h:
        # Ancient H2H (sometimes >10 years old) decays below the effective
        # threshold. Do not multiply an expectation by None or discard the game.
        h2h_recent = [row for row in h2h if (captured - row[0]).days <= 1095]
        h2h_home = weighted(h2h_recent, 0, captured)
        h2h_away = weighted(h2h_recent, 1, captured)
        if h2h_home is not None and h2h_away is not None:
            w = min(0.12, len(h2h_recent) * 0.024)
            home_lambda = (1 - w) * home_lambda + w * h2h_home
            away_lambda = (1 - w) * away_lambda + w * h2h_away
    home_lambda = max(0.15, min(4.5, home_lambda + injuries["home_attack"] + injuries["away_conceded"]))
    away_lambda = max(0.15, min(4.5, away_lambda + injuries["away_attack"] + injuries["home_conceded"]))
    had, hhad, ttg, top = distribution(home_lambda, away_lambda, handicap)
    goal_rank = sorted(zip(TTG, ttg), key=lambda item: item[1], reverse=True)
    # Up to TWO exact JC total-goal buckets, not an invented over/under line.
    chosen = goal_rank[:2] if goal_rank[1][1] >= 0.10 else goal_rank[:1]
    goal_recommendation = {"goals": [label for label, _ in chosen],
                           "individual_probabilities": [round(p, 6) for _, p in chosen],
                           "combined_probability": round(sum(p for _, p in chosen), 6),
                           "selection_rule": "TOP_TWO_IF_SECOND_AT_LEAST_10_PERCENT"}
    base.update(status="RESEARCH_READY", goal_expectation={
        "home": round(home_lambda, 3), "away": round(away_lambda, 3)},
        top_score={"home": top[0], "away": top[1]},
        injury_effect_goals={k: round(v, 4) for k, v in injuries.items()},
        markets={
            "had": market_result(HAD, had, had_odds),
            "hhad": {**market_result(HHAD, hhad, hhad_odds),
                     "signed_home_handicap": handicap},
            "ttg": {**market_result(TTG, ttg, ttg_odds),
                    "goal_selection": goal_recommendation}
        })
    return base


def run(snapshot):
    if snapshot.get("schema_version") != "football-jc-007-v1":
        raise ValueError("UNSUPPORTED_007_SNAPSHOT_CONTRACT")
    captured = when(snapshot["captured_at_utc"])
    date = snapshot["beijing_date"]
    if datetime.fromisoformat(date).strftime("%Y-%m-%d") != date:
        raise ValueError("INVALID_BEIJING_DATE")
    jc_sale_day = snapshot.get("jc_sale_day_beijing")
    if jc_sale_day:
        if jc_sale_day != date:
            raise ValueError("FOOTBALL_JC_SALE_DAY_DATE_MISMATCH")
        from datetime import date as _date
        prefix = "周"+"一二三四五六日"[_date.fromisoformat(jc_sale_day).weekday()]
        for fixture in snapshot.get("games") or []:
            if not str(fixture.get("jc_number") or "").startswith(prefix):
                raise ValueError("FORECAST_MIXED_JC_SALE_DAY")
    rows = snapshot.get("games")
    if not isinstance(rows, list):
        raise ValueError("MISSING_GAMES_ARRAY")
    seen = set()
    results = []
    for game in rows:
        mid = str(game.get("match_id") or "")
        if mid in seen or not mid:
            raise ValueError("DUPLICATE_OR_MISSING_007_MATCH_ID")
        seen.add(mid)
        try:
            row = build_match(game, captured)
        except (ValueError, KeyError, TypeError, OverflowError) as exc:
            row = {"match_id": mid, "jc_number": game.get("jc_number"),
                   "league": game.get("league"), "home_team": game.get("home_team"),
                   "away_team": game.get("away_team"), "kickoff_beijing": game.get("kickoff_beijing"),
                   "status": "REJECTED_BAD_007_FEATURE", "reason": str(exc)[:160],
                   "markets": {k: {"status": "UNAVAILABLE_BAD_SOURCE", "direction": None,
                                  "probabilities": None} for k in MARKETS}}
        results.append(row)
    return {
        "model_version": VERSION,
        "source_schema": snapshot["schema_version"],
        "source_sha256": hashlib.sha256(json.dumps(snapshot, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
        "beijing_date": date, "captured_at_utc": snapshot["captured_at_utc"],
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "game_count": len(results), "games": results,
        "market_scope": list(MARKETS),
        "model_status": "RESEARCH_NOT_VALIDATED",
        "source_status": (
            "LIVE_007_THREE_MARKETS_RECENT_FORM_H2H_WITH_INJURY_AVAILABILITY_UNVERIFIED"
            if (snapshot.get("source_provenance") or {}).get("state") == "LIVE_007_PUBLIC_FIXTURE_HAD_HHAD_TTG_PARTIAL" and (snapshot.get("source_provenance") or {}).get("analysis_coverage", {}).get("parsed", 0)>0
            else "LIVE_007_THREE_MARKETS_FORM_INJURIES_MISSING"
            if (snapshot.get("source_provenance") or {}).get("state") == "LIVE_007_PUBLIC_FIXTURE_HAD_HHAD_TTG_PARTIAL"
            else "LIVE_007_PARTIAL_FIXTURE_AND_TWO_MARKETS"
            if (snapshot.get("source_provenance") or {}).get("state") == "LIVE_007_PUBLIC_FIXTURE_AND_HAD_HHAD_ONLY"
            else "SNAPSHOT_PROVIDED_NO_LIVE_007_CAPTURE_VERIFICATION"),
        "no_claim_of_backtested_accuracy": True,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, help="Timestamped, source-attributed verified 007 football JSON snapshot")
    ap.add_argument("--out", default="football_jc_forecast.json")
    args = ap.parse_args()
    raw = Path(args.input).read_bytes()
    if len(raw) > 12_000_000:
        raise SystemExit("SNAPSHOT_TOO_LARGE")
    data = json.loads(raw)
    outcome = run(data)
    outcome["input_raw_sha256"] = hashlib.sha256(raw).hexdigest()
    dest = Path(args.out)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(outcome, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("FOOTBALL_JC_RESEARCH", outcome["game_count"], "matches", outcome["model_status"])


if __name__ == "__main__":
    main()
