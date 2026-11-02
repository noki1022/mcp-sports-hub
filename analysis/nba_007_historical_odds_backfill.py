#!/usr/bin/env python3
"""Backfill real point-in-time 007 NBA market captures from OWN archived Git reports.

Only existing, originally stored, pre-tip observations qualify. Never fetch
an old date today and pretend its price was available at that old tipoff.
An opening quote without an opening update timestamp is NEVER a snapshot row.
Exact 007 match ID + verified ESPN tipoff + target Beijing date are required.
Crown always means the user-confirmed company ID 3; no alternate substitute.

Output is research-only. User-confirmed raw slot placement is preserved as an
assumption; no independently unproven side-price map is advertised as certified.
No production models, notifications, jobs or betting signals are modified.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

MARKETS = ("JINGCAI_WIN", "JINGCAI_HANDICAP", "JINGCAI_TOTAL",
           "CROWN_HANDICAP", "CROWN_TOTAL")
JC_MAP = {"win_lose": "JINGCAI_WIN", "handicap": "JINGCAI_HANDICAP",
          "total": "JINGCAI_TOTAL"}
CROWN_MAP = {"full_spread": "CROWN_HANDICAP", "full_total": "CROWN_TOTAL"}
CUT_OFF_MINUTES = (30, 120, 720)
MAX_LEAD_HOURS = 72
MIN_LEAD_MINUTES = 3
FORMAT_VERSION = "nba-007-historical-asof-v1"
QUOTE_PROVENANCE = "ACTUAL_ARCHIVED_PAGE_CAPTURE_NOT_BOOKMAKER_TICK"
SLOT_ASSURANCE = "USER_CONFIRMED_DISPLAY_ORDER_RAW_FIELD_MAPPING_NOT_INDEPENDENTLY_PROVEN"


def when(value):
    if not isinstance(value, str):
        return None
    try:
        d = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return d.astimezone(timezone.utc) if d.tzinfo is not None else None
    except ValueError:
        return None


def n(value):
    try:
        if value is None or isinstance(value, bool):
            return None
        f = float(value)
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None


def read_json(path):
    try:
        raw = path.read_text(encoding="utf-8").strip()
        if raw.endswith("\\n"):
            raw = raw[:-2]
        item = json.loads(raw)
        return item if isinstance(item, dict) else None
    except (OSError, ValueError):
        return None


def asof_filename(path, base):
    return str(path.relative_to(base)).replace("\\", "/")


def make_id(date, game_id, nba_id, home, away, tip):
    return (date, str(game_id), str(nba_id), str(home), str(away), tip.isoformat())


def reference_board(root, rejected):
    """Only accept explicit 007 game ID joined to official UTC fixture time."""
    boards = {}
    by_match = defaultdict(set)
    for path in sorted(root.glob("reports/daily/*/*/titan007_*_joined.json")):
        if path.name not in ("titan007_priority_joined.json",
                             "titan007_three_joined.json"):
            continue
        doc = read_json(path)
        if doc is None:
            rejected["BAD_JOIN_DOCUMENT"] += 1
            continue
        requested = str(doc.get("requested_display_date") or "")
        captured = when(doc.get("captured_at_utc"))
        if captured is None or len(requested) != 10:
            rejected["JOIN_CAPTURE_OR_DATE_MISSING"] += 1
            continue
        for game in doc.get("nba_cba_games", []):
            if game.get("league") != "NBA":
                continue
            gid = str(game.get("game_id") or "")
            nid = str(game.get("nba_game_id") or "")
            home, away = str(game.get("home_team") or ""), str(game.get("away_team") or "")
            tip = when(game.get("tipoff_utc"))
            bj = when(game.get("start_time_beijing"))
            if (not gid.isdigit() or not nid.isdigit() or not home or not away or
                tip is None or bj is None or tip != bj or
                (bj + timedelta(hours=8)).date().isoformat() != requested):
                rejected["JOIN_WITHOUT_VERIFIED_IDENTITY_OR_UTC_TIP"] += 1
                continue
            if captured >= tip:
                rejected["JOIN_AFTER_TIPOFF"] += 1
                continue
            key = (requested, gid)
            match_id = make_id(requested, gid, nid, home, away, tip)
            by_match[key].add(match_id)
            boards.setdefault(key, []).append({
                "path": path, "doc": doc, "game": game, "tip": tip,
                "identity": match_id, "captured": captured,
            })
    for key, versions in list(boards.items()):
        if len(by_match[key]) > 1:
            rejected["MUTATED_TEAM_OR_TIPOFF_IDENTITY"] += 1
            del boards[key]
    return boards


def result_index(root, boards, rejected):
    results = {}
    for path in sorted(root.glob("reports/five-market-settled/*/settlement.json")):
        doc = read_json(path)
        if not doc:
            rejected["SETTLEMENT_DOCUMENT_UNREADABLE"] += 1
            continue
        date = str(doc.get("beijing_date") or "")
        for g in doc.get("games", []):
            gid = str(g.get("game_id") or "")
            if not gid or not g.get("home_team") or not g.get("away_team"):
                rejected["SETTLEMENT_TEAM_ID_MISSING"] += 1
                continue
            hp, ap = n(g.get("home_points")), n(g.get("away_points"))
            key = (date, gid)
            if hp is None or ap is None or key not in boards:
                continue
            board = boards[key][0]
            fixture = board["game"]
            if (str(g.get("home_team")) != str(fixture.get("home_team")) or
                str(g.get("away_team")) != str(fixture.get("away_team"))):
                rejected["SETTLED_TEAM_ID_DISAGREEMENT"] += 1
                continue
            if key in results:
                rejected["DUPLICATE_SETTLEMENT_GAME"] += 1
                del results[key]
                continue
            results[key] = {"home_points": int(hp), "away_points": int(ap),
                            "margin": int(hp-ap), "total": int(hp+ap)}
    return results


def first_side_result(key, line, outcome):
    margin, total = outcome["margin"], outcome["total"]
    if key == "JINGCAI_WIN":
        x = margin
    elif key == "JINGCAI_HANDICAP":
        x = margin + line
    elif key == "CROWN_HANDICAP":
        x = margin - line  # Crown raw +line denotes HOME GIVES
    elif key in ("JINGCAI_TOTAL", "CROWN_TOTAL"):
        x = total - line
    else:
        raise ValueError("UNKNOWN_MARKET")
    return "PUSH" if abs(x) < 1e-9 else "FIRST_SIDE" if x > 0 else "SECOND_SIDE"


def build_record(board, market, captured, cur, source_path,
                 *, source, origin="current", settled=None, out_rejected=None):
    reject = out_rejected if out_rejected is not None else Counter()
    game = board["game"]
    tip = board["tip"]
    if captured is None:
        reject["SOURCE_TIMESTAMP_MISSING"] += 1
        return None
    lead = (tip-captured).total_seconds()/60
    if lead < MIN_LEAD_MINUTES or lead > MAX_LEAD_HOURS*60:
        reject["OUTSIDE_VALID_PRETIP_CAPTURE_WINDOW"] += 1
        return None
    if origin != "current":
        reject["NOT_TIME_STAMPED_CURRENT_QUOTE"] += 1
        return None
    line = None if market == "JINGCAI_WIN" else n(cur.get("line"))
    if market != "JINGCAI_WIN" and line is None:
        reject["MISSING_LINE"] += 1
        return None
    if market.endswith("TOTAL") and not 80 <= line <= 400:
        reject["TOTAL_LINE_INVALID"] += 1
        return None
    if market.endswith("HANDICAP") and not -80 <= line <= 80:
        reject["HANDICAP_LINE_INVALID"] += 1
        return None
    if market.startswith("JINGCAI"):
        first, second = n(cur.get("first_side")), n(cur.get("second_side"))
        if (first is None or second is None or
            not (1 < first < 30 and 1 < second < 30)):
            reject["JINGCAI_PRICE_PAIR_INVALID"] += 1
            return None
        units = "DECIMAL"
        book = "007_JINGCAI_REFERENCE"
    else:
        first, second = n(cur.get("first_side_water")), n(cur.get("second_side_water"))
        if (first is None or second is None or
            not (0 < first < 9 and 0 < second < 9)):
            reject["CROWN_PRICE_PAIR_INVALID"] += 1
            return None
        units = "HK_WATER"
        book = "007_COMPANY_ID_3_CROWN"
    capture_utc = captured.isoformat().replace("+00:00", "Z")
    dated = (board["identity"][0], board["identity"][1])
    result = {
        "schema_version": FORMAT_VERSION, "beijing_date": dated[0],
        "game_id": dated[1], "nba_game_id": board["identity"][2],
        "home_team": game["home_team"], "away_team": game["away_team"],
        "tipoff_utc": tip.isoformat().replace("+00:00", "Z"),
        "market": market, "bookmaker": book,
        "company_id": "3" if market.startswith("CROWN") else None,
        "quote_capture_utc": capture_utc,
        "price_observed_lead_minutes": round(lead, 3),
        "timestamp_type": QUOTE_PROVENANCE,
        "line": line,
        "signed_home_handicap": (
            line if market == "JINGCAI_HANDICAP"
            else -line if market == "CROWN_HANDICAP" else None),
        "price_units": units, "raw_slot1_price": first,
        "raw_slot2_price": second,
        "slot_mapping_assurance": SLOT_ASSURANCE,
        "actual_bookmaker_last_update_utc": None,
        "price_side_probability_verified": False,
        "source_archive_file": asof_filename(source_path, board["base"]),
        "research_asof_line_eligible": True,
        "production_fusion_eligible": False,
        "settled_result": settled,
        "observed_first_side_result": (
            first_side_result(market, line, settled) if settled else None),
        "opening_line_time_attested": False,
        "opening_line_imported": False,
    }
    return result


def reconstruct(root):
    root = Path(root)
    rejected = Counter()
    boards = reference_board(root, rejected)
    results = result_index(root, boards, rejected)
    exact_candidates = {}
    ambiguities = set()
    candidate_count = Counter()

    def ingest(record):
        if record is None:
            return
        key = (record["beijing_date"], record["game_id"],
               record["market"], record["quote_capture_utc"])
        candidate_count[record["market"]] += 1
        if key in ambiguities:
            return
        old = exact_candidates.get(key)
        if old is not None:
            comparable = ("line", "raw_slot1_price", "raw_slot2_price",
                          "nba_game_id", "tipoff_utc")
            if any(old[x] != record[x] for x in comparable):
                rejected["CONFLICTING_SAME_INSTANT_GAME_MARKET_QUOTE"] += 1
                ambiguities.add(key)
                del exact_candidates[key]
            return
        exact_candidates[key] = record

    for day_id, versions in boards.items():
        settled = results.get(day_id)
        for b in versions:
            b["base"] = root
            # Only the actual dated ID 3 quote attached to the verified board.
            # Older scripts use the fixed id=3 source without a stored field.
            source_id = str(b["doc"].get("crown_source_id") or
                            b["game"].get("market_source_id") or "3")
            if source_id != "3":
                rejected["CROWN_SOURCE_ID_NOT_3"] += 1
                continue
            source_capture = when(b["game"].get("quote_captured_at_utc") or
                                  b["doc"].get("crown_quote_captured_at_utc") or
                                  b["doc"].get("captured_at_utc"))
            for source_key, market in CROWN_MAP.items():
                vals = ((b["game"].get("markets") or {}).get(source_key) or {})
                current = vals.get("current") or {}
                if vals.get("status") in ("CROWN_QUOTE_NOT_VERIFIED", "NO_VERIFIED_ID3_SPREAD",
                                          "NO_VERIFIED_ID3_TOTAL"):
                    continue
                if not current:
                    continue
                ingest(build_record(b, market, source_capture, current, b["path"],
                                    source="JOINED_VERIFIED_ID3",
                                    settled=settled, out_rejected=rejected))

            # JC parser archives exist only for some daily slots. Never invent
            # missing 007 XML price rows using market directions.
            jc_file = b["path"].parent / "nba_jingcai_three_market.json"
            jc = read_json(jc_file) if jc_file.is_file() else None
            if jc:
                shadow = jc.get("jc_007_public_odds_shadow") or {}
                if shadow.get("source", "").endswith("/xml/odds_jc_lq.txt"):
                    capture = when(shadow.get("captured_at_utc"))
                    for q in shadow.get("games", []):
                        if str(q.get("game_id")) != day_id[1]:
                            continue
                        if str(q.get("nba_game_id")) != b["identity"][2]:
                            rejected["JC_NBA_ID_MISMATCH"] += 1
                            continue
                        for source_key, market in JC_MAP.items():
                            part = (q.get("markets") or {}).get(source_key) or {}
                            if part.get("status") != "OBSERVED":
                                continue
                            current = ((part.get("data") or {}).get("current") or {})
                            ingest(build_record(b, market, capture, current, jc_file,
                                                source="007_JC_ORIGINAL_XML_ARCHIVE",
                                                settled=settled, out_rejected=rejected))

            # Supplement previously frozen FIRST-PARTY 007 JC current prices
            # only where the report explicitly preserved its raw two prices.
            ff = b["path"].parent / "nba_five_market_forecast.json"
            forecast = read_json(ff) if ff.is_file() else None
            if forecast and forecast.get("schema_version") == "nba-five-markets-v1":
                for game in forecast.get("games", []):
                    if str(game.get("game_id")) != day_id[1]:
                        continue
                    if str(game.get("nba_game_id")) != b["identity"][2]:
                        rejected["FORECAST_NBA_ID_MISMATCH"] += 1
                        continue
                    for market in MARKETS[:3]:
                        m = (game.get("markets") or {}).get(market) or {}
                        slots = m.get("raw_price_slots") or {}
                        if (m.get("status") != "DIRECTION_ISSUED" or
                            m.get("source") != "007_JINGCAI" or not slots):
                            continue
                        current = {"line": m.get("line"),
                                   "first_side": slots.get("first"),
                                   "second_side": slots.get("second")}
                        ingest(build_record(b, market, when(m.get("captured_at_utc")),
                                            current, ff, source="FROZEN_JC_QUOTE",
                                            settled=settled, out_rejected=rejected))

    # Earlier P0 hourly snapshots are durable normalized copies produced from
    # the same ID3 joined 007 board. They may contain actual intermediate
    # observations that do not appear in the daily report directory.
    # Confirm exact date, ID, home, away, and display clock against a
    # separately verified ESPN+007 join; no fuzzy matching or new game IDs.
    for path in sorted(root.glob("reports/hourly/*/*.json")):
        doc = read_json(path)
        if (not doc or doc.get("schema_version") != "titan007-market-snapshot-v1"
                or "bf.titan007.com/nba_Oddsdata.aspx" not in str(doc.get("source_url") or "")):
            continue
        target = str(doc.get("target_date") or "")
        capture = when(doc.get("captured_at_utc"))
        if capture is None:
            rejected["HOURLY_SOURCE_TIMESTAMP_MISSING"] += 1
            continue
        for game in doc.get("games",[]):
            key = (target,str(game.get("game_id") or ""))
            if game.get("league") != "NBA" or key not in boards:
                continue
            b = boards[key][0]
            b["base"] = root
            known = b["game"]
            if (game.get("display_date") != target or
                game.get("home_team") != known.get("home_team") or
                game.get("away_team") != known.get("away_team") or
                game.get("display_clock") != known.get("display_clock")):
                rejected["HOURLY_SOURCE_IDENTITY_MISMATCH"] += 1
                continue
            for source_key,market in CROWN_MAP.items():
                current=(((game.get("markets") or {}).get(source_key) or {}).get("current") or {})
                if current:
                    ingest(build_record(
                        b,market,capture,current,path,
                        source="HOURLY_NORMALIZED_FROM_VERIFIED_007_ID3_BOARD",
                        settled=results.get(key),out_rejected=rejected))

    # ID3 pretip source archive may contain additional observation slots.
    for path in sorted(root.glob("reports/top10/*/*.json")):
        doc = read_json(path)
        if not doc or doc.get("schema_version") != "nba-007-visible-top10-v1":
            continue
        target = str(doc.get("target_date") or "")
        for game in doc.get("games", []):
            key = (target, str(game.get("game_id") or ""))
            if key not in boards:
                continue
            b = boards[key][0]
            b["base"] = root
            for source_key, market in CROWN_MAP.items():
                for row in (((game.get("markets") or {}).get(source_key) or {})
                            .get("companies") or []):
                    if str(row.get("company_id")) != "3":
                        continue
                    if row.get("source") != "DATED_007_COMPANY_ID":
                        # Never treat an archived stale fallback as a fresh tick.
                        rejected["ARCHIVED_FALLBACK_IS_NOT_NEW_TICK"] += 1
                        continue
                    current = row.get("current") or {}
                    capture = when(row.get("source_capture_utc"))
                    ingest(build_record(b, market, capture, current, path,
                                        source="TOP10_ID3_ORIGINAL_SNAPSHOT",
                                        settled=results.get(key), out_rejected=rejected))

    observations = sorted(exact_candidates.values(), key=lambda r: (
        r["beijing_date"], r["game_id"], r["market"], r["quote_capture_utc"]))
    frozen = {}
    stats = {}
    for minutes in CUT_OFF_MINUTES:
        chosen = {}
        for row in observations:
            if row["price_observed_lead_minutes"] < minutes:
                continue
            # One observation per game/market/cutoff, not each market tick as
            # a statistically independent training game.
            key = (row["beijing_date"], row["game_id"], row["market"])
            if key not in chosen or row["quote_capture_utc"] > chosen[key]["quote_capture_utc"]:
                chosen[key] = row
        subset = []
        for row in sorted(chosen.values(), key=lambda x: (
                x["beijing_date"], x["game_id"], x["market"])):
            res = {**row,
                   "research_cutoff_minutes_before_tip": minutes,
                   "labeled_for_line_outcome": row["settled_result"] is not None,
                   "train_price_side_probabilities": False,
                   "same_game_multi_cutoff_dependent": True}
            subset.append(res)
        frozen[minutes] = subset
        stats[minutes] = {
            "market_rows": len(subset),
            "distinct_games": len({(r["beijing_date"],r["game_id"]) for r in subset}),
            "labeled_market_rows": sum(r["labeled_for_line_outcome"] for r in subset),
            "labeled_distinct_games": len({(r["beijing_date"],r["game_id"])
                                           for r in subset if r["labeled_for_line_outcome"]}),
            "labeled_by_market": {
                k:sum(r["market"] == k and r["labeled_for_line_outcome"] for r in subset)
                for k in MARKETS},
            "market_rows_by_market": {
                k:sum(r["market"] == k for r in subset) for k in MARKETS},
        }
    report = {
        "schema_version": FORMAT_VERSION,
        "input": "REPOSITORY_OWNED_ARCHIVED_007_POINT_IN_TIME_REPORTS_ONLY",
        "archive_fixture_ids": len(boards),
        "settled_fixture_ids": len(results),
        "observed_quote_rows": len(observations),
        "observation_game_markets": len({(r["beijing_date"],r["game_id"],r["market"])
                                         for r in observations}),
        "observation_games": len({(r["beijing_date"],r["game_id"]) for r in observations}),
        "quote_observation_counts": dict(candidate_count),
        "time_cutoffs": stats,
        "rejections": dict(sorted(rejected.items())),
        "no_historical_timestamps_invented": True,
        "not_independent_samples": "Multiple company timestamps, markets and cutoffs of the same game",
        "opening_prices_without_opening_timestamp": "EXCLUDED",
        "side_price_probability_training": "BLOCKED_UNVERIFIED_RAW_SLOT_MAPPING",
        "closing_benchmark_from_future_fetch": "EXCLUDED",
        "source_provider_page_time_not_bookmaker_update": True,
        "crown_company_id": "3",
        "production_model_changed": False,
        "fit_or_strategy_promotion": False,
    }
    return observations, frozen, report



def movements_asof_30m(frozen):
    """Compute only changes between independently captured pre-tip quotes.

    Differences in these frozen source fetches are research features, not
    proofs of actual bookmaker tick time. Same fetch cannot be treated as
    two independent market changes. Handicap signed home perspective is
    retained explicitly and different JC/Crown raw sign conventions respected.
    """
    indexed={cutoff:{(r["beijing_date"],r["game_id"],r["market"]):r
                     for r in frozen[cutoff]} for cutoff in CUT_OFF_MINUTES}
    output=[]
    stats=Counter()
    for key, last in sorted(indexed[30].items()):
        if last["market"] not in MARKETS:
            continue
        snapshots={n:indexed[n].get(key) for n in CUT_OFF_MINUTES}
        available={str(n):{
            "source_capture_utc":r["quote_capture_utc"],
            "lead_minutes":r["price_observed_lead_minutes"],
            "asof_capture_age_minutes":round(
                r["price_observed_lead_minutes"]-n,3),
            "line":r["line"],
            "signed_home_handicap":r["signed_home_handicap"],
            "raw_slot1_price":r["raw_slot1_price"],
            "raw_slot2_price":r["raw_slot2_price"],
            "captured_within_120_minutes_before_cutoff":(
                r["price_observed_lead_minutes"]-n<=120),
        } for n,r in snapshots.items() if r}
        changes={}
        for early,late in ((720,120),(120,30),(720,30)):
            a,b=snapshots[early],snapshots[late]
            name=f"{early}_to_{late}"
            if not a or not b:
                changes[name]={"status":"MISSING_EARLIER_OR_LATER_ASOF"}
                continue
            if a["quote_capture_utc"]==b["quote_capture_utc"]:
                changes[name]={"status":"SAME_SOURCE_CAPTURE_NO_NEW_OBSERVATION"}
                continue
            if a["quote_capture_utc"]>b["quote_capture_utc"]:
                raise AssertionError("BACKWARD_QUOTE_CAPTURE_CHANGE")
            delta_line=None if a["line"] is None else round(b["line"]-a["line"],3)
            delta_home_handicap=(
                round(b["signed_home_handicap"]-a["signed_home_handicap"],3)
                if a["signed_home_handicap"] is not None else None)
            changes[name]={
                "status":"OBSERVED_DISTINCT_PRETIP_CAPTURES",
                "line_change":delta_line,
                "signed_home_handicap_change":delta_home_handicap,
                "raw_slot1_price_change":round(b["raw_slot1_price"]-a["raw_slot1_price"],5),
                "raw_slot2_price_change":round(b["raw_slot2_price"]-a["raw_slot2_price"],5),
                "line_changed":delta_line is not None and abs(delta_line)>1e-9,
                "old_capture_utc":a["quote_capture_utc"],
                "new_capture_utc":b["quote_capture_utc"],
            }
            stats[f"{name}_independent_capture_pairs"]+=1
            if delta_line is not None and abs(delta_line)>1e-9:
                stats[f"{name}_changed_line_pairs"]+=1
        output.append({
            "schema_version":"nba-007-market-movement-asof-v1",
            "beijing_date":last["beijing_date"],
            "game_id":last["game_id"],
            "nba_game_id":last["nba_game_id"],
            "home_team":last["home_team"],"away_team":last["away_team"],
            "tipoff_utc":last["tipoff_utc"],
            "market":last["market"],
            "bookmaker":last["bookmaker"],
            "source_capture_count_across_cutoffs":len({
                r["quote_capture_utc"] for r in snapshots.values() if r}),
            "cutoffs":available, "changes":changes,
            "settled_result":last["settled_result"],
            "first_side_line_outcome":last["observed_first_side_result"],
            "has_outcome":last["settled_result"] is not None,
            "market_probability_calibration_eligible":False,
            "valid_for_research_line_movement":True,
            "warning":"Quoted source fetch times, NOT bookmaker update times",
        })
    stats["rows"]=len(output)
    stats["settled_rows"]=sum(x["has_outcome"] for x in output)
    stats["distinct_games"]=len({(x["beijing_date"],x["game_id"]) for x in output})
    return output,dict(sorted(stats.items()))


def export(root, out):
    observations, frozen, report = reconstruct(root)
    movement_rows, movement_stats = movements_asof_30m(frozen)
    report["line_movement_30m"] = movement_stats
    target = Path(out)
    target.mkdir(parents=True, exist_ok=True)
    paths = {"observations": target / "all_archived_pretip_007_quotes.jsonl"}
    def dump(path, rows):
        path.write_text("".join(json.dumps(r, ensure_ascii=False, sort_keys=True,
                                           allow_nan=False)+"\n" for r in rows),
                        encoding="utf-8")
    dump(paths["observations"], observations)
    paths["line_movement"] = target / "observed_line_movements_asof_30m.jsonl"
    dump(paths["line_movement"], movement_rows)
    for minutes, rows in frozen.items():
        path = target / f"frozen_{minutes}m_007_five_markets.jsonl"
        dump(path, rows)
        paths[str(minutes)] = path
    checks = {name: hashlib.sha256(path.read_bytes()).hexdigest()
              for name, path in paths.items()}
    report["output_sha256"] = checks
    (target / "report.json").write_text(json.dumps(report, ensure_ascii=False,
                                      indent=2, sort_keys=True)+"\n", encoding="utf-8")
    print("NBA_007_ARCHIVED_HISTORICAL_BACKFILL",json.dumps({
        "observed": report["observed_quote_rows"],
        "fixture_ids": report["archive_fixture_ids"],
        "settled_fixture_ids": report["settled_fixture_ids"],
        "cutoffs": report["time_cutoffs"],
        "rejections": report["rejections"],
        "movement": report["line_movement_30m"],
        "production_changed": False},ensure_ascii=False,sort_keys=True))
    return report


def self_test():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        daily = root / "reports/daily/2026-11-01/2130"
        settle = root / "reports/five-market-settled/2026-11-01"
        daily.mkdir(parents=True);settle.mkdir(parents=True)
        def save(path,obj):
            path.write_text(json.dumps(obj,ensure_ascii=False),encoding="utf-8")
        game={"league":"NBA","game_id":"700001","nba_game_id":"401000000",
              "home_team":"主队","away_team":"客队",
              "start_time_beijing":"2026-11-01T08:00:00+08:00",
              "tipoff_utc":"2026-11-01T00:00:00Z","market_source_id":"3",
              "markets":{"full_spread":{"current":{"line":4.5,"first_side_water":.95,
                                                   "second_side_water":.95}},
                         "full_total":{"current":{"line":221.5,"first_side_water":.91,
                                                  "second_side_water":.91}}}}
        joined={"captured_at_utc":"2026-10-31T22:00:00Z",
                "crown_source_id":"3","requested_display_date":"2026-11-01",
                "nba_cba_games":[game]}
        save(daily/"titan007_priority_joined.json",joined)
        jc={"jc_007_public_odds_shadow":{
             "source":"https://jc.titan007.com/xml/odds_jc_lq.txt",
             "captured_at_utc":"2026-10-31T22:01:00Z",
             "games":[{"game_id":"700001","nba_game_id":"401000000",
                       "markets":{"win_lose":{"status":"OBSERVED","data":{
                                   "opening":{"first_side":1.30,"second_side":3.0},
                                   "current":{"first_side":1.45,"second_side":2.40}}},
                                  "handicap":{"status":"OBSERVED","data":{
                                   "current":{"line":-5.5,"first_side":1.8,"second_side":1.65}}},
                                  "total":{"status":"OBSERVED","data":{
                                   "current":{"line":220.5,"first_side":1.65,"second_side":1.75}}}}}]}}
        save(daily/"nba_jingcai_three_market.json",jc)
        save(settle/"settlement.json",{
            "beijing_date":"2026-11-01","games":[{
            "game_id":"700001","home_team":"主队","away_team":"客队",
            "home_points":110,"away_points":100}]})
        rows, cuts, report = reconstruct(root)
        assert len(rows)==5, (len(rows),report)
        assert report["archive_fixture_ids"]==1 and report["settled_fixture_ids"]==1
        assert len(cuts[30])==5 and len(cuts[120])==2  # JC captured at T-119m; ID3 at T-120m
        assert cuts[30][0]["settled_result"]["home_points"]==110
        assert any(r["market"]=="CROWN_HANDICAP" and
                   r["signed_home_handicap"]==-4.5 and
                   r["observed_first_side_result"]=="FIRST_SIDE" for r in rows)
        assert any(r["market"]=="JINGCAI_HANDICAP" and
                   r["signed_home_handicap"]==-5.5 for r in rows)
        assert cuts[30][0]["price_side_probability_verified"] is False
        movements, mstats = movements_asof_30m(cuts)
        assert len(movements)==5 and mstats["rows"]==5
        assert all(not x["market_probability_calibration_eligible"] for x in movements)
        assert all(x["changes"]["120_to_30"]["status"] ==
                   "SAME_SOURCE_CAPTURE_NO_NEW_OBSERVATION"
                   for x in movements if x["market"].startswith("CROWN"))
        assert all(x["changes"]["120_to_30"]["status"] ==
                   "MISSING_EARLIER_OR_LATER_ASOF"
                   for x in movements if x["market"].startswith("JINGCAI"))
        assert all(x["cutoffs"]["30"]["captured_within_120_minutes_before_cutoff"]
                   for x in movements)
        # A retroactively fetched past-date market is never backfilled with
        # a guessed pre-game timestamp; reject quotes recorded after the tip.
        joined["captured_at_utc"]="2026-11-01T00:01:00Z"
        save(daily/"titan007_priority_joined.json",joined)
        after, _, state = reconstruct(root)
        assert not after and state["archive_fixture_ids"]==0
        print("NBA_007_ARCHIVED_ODDS_POINT_IN_TIME_SELF_TEST_PASS")


if __name__=="__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--out", default="/tmp/nba-007-historical-archive")
    parser.add_argument("--self-test",action="store_true")
    args=parser.parse_args()
    if args.self_test:
        self_test()
    else:
        export(args.repo_root,args.out)
