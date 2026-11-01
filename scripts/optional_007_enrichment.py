#!/usr/bin/env python3
"""Best-effort 007 multi-company enrichment with a canonical ID3 fallback.

This helper is deliberately non-blocking for production analysis: optional
company capture or consensus failures create schema-compatible degraded
artifacts and return exit code 0. Missing/corrupt primary joined-board input
remains a hard error because it is required by the core workflow.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "analysis"))

CROWN_ID = "3"
CROWN_MAPPING = "USER_CONFIRMED_FIXED_MAPPING_ID3_EQUALS_CROWN"
VALIDATED_IDS = ["3", "1", "2", "8", "9", "10", "19", "20", "24", "31"]
MARKETS = ("full_spread", "full_total")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: str | Path) -> dict[str, Any]:
    obj = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise ValueError(f"JSON_OBJECT_REQUIRED:{path}")
    return obj


def write_json(path: str | Path, obj: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(target.suffix + ".tmp")
    temp.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    temp.replace(target)


def nba_games(board: dict[str, Any]) -> list[dict[str, Any]]:
    return [g for g in board.get("nba_cba_games", [])
            if g.get("league") == "NBA" and g.get("game_id") is not None]


def build_fallback_top10(board: dict[str, Any], reason: str) -> tuple[dict, dict]:
    """Retain only the already-captured canonical ID3 rows; invent no other quote."""
    captured = (board.get("crown_quote_captured_at_utc")
                or board.get("captured_at_utc"))
    completed = utc_now()
    snap_games = []
    compare_games = []

    for game in nba_games(board):
        gid = str(game["game_id"])
        snap_markets = {}
        compare_markets = {}
        for kind in MARKETS:
            source = ((game.get("markets") or {}).get(kind) or {})
            current = source.get("current") or {}
            companies = []
            line = current.get("line")
            if (str(game.get("market_source_id") or CROWN_ID) == CROWN_ID
                    and line is not None):
                quote = {
                    "display_rank": None,
                    "company_display": "皇冠（007机构ID 3）",
                    "company_id": CROWN_ID,
                    "market": kind,
                    "opening": source.get("opening") or {},
                    "current": current,
                    "side_orientation": "UNVERIFIED_RAW_SLOTS",
                    "source": "DATED_007_COMPANY_ID",
                    "source_capture_utc": captured,
                }
                companies.append(quote)

            state = ("CANONICAL_ID3_ONLY" if companies
                     else "AUXILIARY_CAPTURE_UNAVAILABLE")
            snap_markets[kind] = {
                "status": state,
                "companies": companies,
                "company_ids": [CROWN_ID] if companies else [],
                "source_id_order_unverified": True,
            }
            lines = []
            if line is not None and companies:
                try:
                    lines = [float(line)]
                except (TypeError, ValueError):
                    lines = []
            compare_markets[kind] = {
                "status": state,
                "company_count": len(companies),
                "crown_id3_archived": False,
                "median_line": lines[0] if lines else None,
                "line_min": lines[0] if lines else None,
                "line_max": lines[0] if lines else None,
                "last_capture_company_changes": [],
                "companies": companies,
                "reason": reason,
            }

        snap_games.append({
            "game_id": gid,
            "nba_game_id": str(game.get("nba_game_id") or ""),
            "markets": snap_markets,
        })
        compare_games.append({"game_id": gid, "markets": compare_markets})

    snapshot = {
        "schema_version": "nba-007-visible-top10-v1",
        "target_date": board.get("requested_display_date"),
        "captured_at_utc": board.get("captured_at_utc"),
        "collection_completed_at_utc": completed,
        "quote_timestamp": "CANONICAL_ID3_CAPTURE_TIME_ONLY",
        "company_order": "CANONICAL_ID3_ONLY_NO_MULTI_COMPANY_RANKING",
        "candidate_ids": [CROWN_ID],
        "source_audit": [{
            "id": CROWN_ID,
            "status": "REUSED_CANONICAL_CROSS_DATE_JOIN",
            "reason": reason,
        }, {
            "status": "OPTIONAL_MULTI_COMPANY_CAPTURE_DEGRADED",
            "reason": reason,
        }],
        "games": snap_games,
        "model_probability_adjusted": False,
        "decision": "NO_BET",
        "degraded": True,
    }
    comparison = {
        "schema_version": "nba-007-top10-comparison-v1",
        "target_date": board.get("requested_display_date"),
        "captured_at_utc": board.get("captured_at_utc"),
        "games": compare_games,
        "decision": "NO_BET",
        "model_probability_adjusted": False,
        "company_ranking_verified": False,
        "degraded": True,
        "caveat": "Optional multi-company capture unavailable; only canonical 007 ID3 quotes already present in the primary joined board are retained. No other company quotes are invented.",
    }
    return snapshot, comparison


def build_fallback_consensus(board: dict[str, Any], reason: str) -> dict:
    rows = []
    for game in nba_games(board):
        markets = {}
        for kind in MARKETS:
            markets[kind] = {
                "status": "AUXILIARY_CONSENSUS_UNAVAILABLE",
                "consensus_available": False,
                "company_count": 0,
                "effective_company_count": 0,
                "company_ids": [],
                "effective_company_ids": [],
                "median_line": None,
                "main_line": None,
                "main_line_status": "AUXILIARY_CAPTURE_UNAVAILABLE",
                "main_line_company_count": 0,
                "same_line_price_consensus": {
                    "status": "AUXILIARY_CONSENSUS_UNAVAILABLE",
                    "company_count": 0,
                    "company_ids": [],
                    "first_side_probability": None,
                    "second_side_probability": None,
                },
                "rejected": {"OPTIONAL_ENRICHMENT_FAILURE": 1},
            }
        rows.append({
            "game_id": str(game["game_id"]),
            "nba_game_id": game.get("nba_game_id"),
            "home_team": game.get("home_team"),
            "away_team": game.get("away_team"),
            "tipoff_beijing": game.get("start_time_beijing"),
            "markets": markets,
        })
    return {
        "schema_version": "nba-007-market-consensus-unavailable-v1",
        "target_date": board.get("requested_display_date"),
        "board_capture_utc": board.get("captured_at_utc"),
        "collection_completed_at_utc": None,
        "crown_company_id": CROWN_ID,
        "crown_company_name": "皇冠",
        "identity_mapping": CROWN_MAPPING,
        "validated_company_ids": VALIDATED_IDS,
        "company_names_and_ranking_verified": False,
        "minimum_companies_for_consensus": 3,
        "games": rows,
        "game_count": len(rows),
        "consensus_market_count": 0,
        "possible_market_count": len(rows) * 2,
        "model_probability_fusion": "DISABLED_OPTIONAL_ENRICHMENT_UNAVAILABLE",
        "market_price_consensus": "UNAVAILABLE_SHADOW_ONLY",
        "water_side_mapping": "USER_CONFIRMED_FIRST_HOME_OR_OVER",
        "moneyline_coverage": "NO_DIRECT_MULTI_COMPANY_H2H_QUOTES_COLLECTED",
        "decision": "NO_BET",
        "degraded": True,
        "degraded_reason": reason,
    }


def write_status(path: str | None, state: str, reason: str | None,
                 started: float, timeout: int) -> None:
    if not path:
        return
    write_json(path, {
        "state": state,
        "reason": reason,
        "elapsed_seconds": round(time.monotonic() - started, 2),
        "timeout_seconds": timeout,
        "generated_at_utc": utc_now(),
        "production_blocking": False,
    })


def run_collect(args: argparse.Namespace) -> int:
    started = time.monotonic()
    board = read_json(args.joined)  # Primary input errors must remain visible.
    command = [
        sys.executable, str(ROOT / "scripts" / "titan007_top10_companies.py"),
        "--joined", str(Path(args.joined).resolve()),
        "--out", str(Path(args.out).resolve()),
        "--analysis", str(Path(args.analysis).resolve()),
    ]
    if args.history_root:
        command.extend(["--history-root", str(Path(args.history_root).resolve())])

    failure = None
    try:
        proc = subprocess.run(command, cwd=ROOT, capture_output=True, text=True,
                              timeout=args.timeout, check=False)
        if proc.returncode != 0:
            failure = f"COLLECT_EXIT_{proc.returncode}: {(proc.stderr or proc.stdout)[-400:]}"
        else:
            snap = read_json(args.out)
            comp = read_json(args.analysis)
            if (snap.get("schema_version") != "nba-007-visible-top10-v1"
                    or comp.get("schema_version") != "nba-007-top10-comparison-v1"
                    or len(snap.get("games", [])) != len(nba_games(board))
                    or len(comp.get("games", [])) != len(nba_games(board))):
                failure = "COLLECT_OUTPUT_SCHEMA_OR_GAME_COUNT_INVALID"
    except subprocess.TimeoutExpired:
        failure = f"COLLECT_TIMEOUT_AFTER_{args.timeout}_SECONDS"
    except Exception as exc:
        failure = f"COLLECT_OUTPUT_INVALID:{type(exc).__name__}:{str(exc)[:220]}"

    if failure:
        snapshot, comparison = build_fallback_top10(board, failure)
        write_json(args.out, snapshot)
        write_json(args.analysis, comparison)
        write_status(args.status, "DEGRADED_CANONICAL_ID3_ONLY", failure,
                     started, args.timeout)
        print("OPTIONAL_007_MULTI_COMPANY_CAPTURE_DEGRADED",
              "PRIMARY_PIPELINE_CONTINUES", failure[:260], flush=True)
    else:
        write_status(args.status, "LIVE_MULTI_COMPANY_CAPTURE", None,
                     started, args.timeout)
        print("OPTIONAL_007_MULTI_COMPANY_CAPTURE_OK",
              len(snap.get("games", [])), "games", flush=True)
    return 0


def run_consensus(args: argparse.Namespace) -> int:
    started = time.monotonic()
    board = read_json(args.joined)
    # The top-ten artifact is auxiliary too: if it is missing or malformed,
    # let the builder fail inside the guarded block and emit an unavailable
    # consensus artifact rather than interrupting the production chain.
    command = [
        sys.executable, str(ROOT / "analysis" / "nba_market_consensus.py"),
        "--joined", str(Path(args.joined).resolve()),
        "--top10", str(Path(args.top10).resolve()),
        "--out", str(Path(args.out).resolve()),
    ]
    failure = None
    try:
        proc = subprocess.run(command, cwd=ROOT, capture_output=True, text=True,
                              timeout=args.timeout, check=False)
        if proc.returncode != 0:
            failure = f"CONSENSUS_EXIT_{proc.returncode}: {(proc.stderr or proc.stdout)[-400:]}"
        else:
            result = read_json(args.out)
            if (not str(result.get("schema_version", "")).startswith("nba-007-market-consensus-")
                    or result.get("identity_mapping") != CROWN_MAPPING
                    or len(result.get("games", [])) != len(nba_games(board))):
                failure = "CONSENSUS_OUTPUT_SCHEMA_OR_GAME_COUNT_INVALID"
    except subprocess.TimeoutExpired:
        failure = f"CONSENSUS_TIMEOUT_AFTER_{args.timeout}_SECONDS"
    except Exception as exc:
        failure = f"CONSENSUS_OUTPUT_INVALID:{type(exc).__name__}:{str(exc)[:220]}"

    if failure:
        write_json(args.out, build_fallback_consensus(board, failure))
        write_status(args.status, "DEGRADED_NO_CONSENSUS", failure,
                     started, args.timeout)
        print("OPTIONAL_007_CONSENSUS_DEGRADED",
              "PRIMARY_PIPELINE_CONTINUES", failure[:260], flush=True)
    else:
        write_status(args.status, "LIVE_CONSENSUS_OR_VALID_NO_QUOTES", None,
                     started, args.timeout)
        print("OPTIONAL_007_CONSENSUS_OK",
              result.get("consensus_market_count"), "/",
              result.get("possible_market_count"), flush=True)
    return 0


def self_test() -> None:
    board = {
        "requested_display_date": "2026-11-02",
        "captured_at_utc": "2026-11-01T12:00:00Z",
        "crown_quote_captured_at_utc": "2026-11-01T12:00:00Z",
        "nba_cba_games": [{
            "game_id": "728165", "nba_game_id": "nba728165", "league": "NBA",
            "home_team": "主队", "away_team": "客队",
            "market_source_id": "3",
            "start_time_beijing": "2026-11-02T08:00:00+08:00",
            "markets": {
                "full_spread": {"current": {
                    "line": 5.5, "first_side_water": 0.91, "second_side_water": 0.95}},
                "full_total": {"current": {
                    "line": 224.5, "first_side_water": 0.92, "second_side_water": 0.94}},
            },
        }],
    }
    snap, comp = build_fallback_top10(board, "SELF_TEST_SIMULATED_TIMEOUT")
    assert snap["degraded"] is True and comp["degraded"] is True
    for kind in MARKETS:
        rows = comp["games"][0]["markets"][kind]["companies"]
        assert len(rows) == 1 and rows[0]["company_id"] == CROWN_ID
        assert rows[0]["source"] == "DATED_007_COMPANY_ID"
    assert snap["candidate_ids"] == [CROWN_ID]
    assert comp["company_ranking_verified"] is False

    consensus = build_fallback_consensus(board, "SELF_TEST_SIMULATED_TIMEOUT")
    assert consensus["game_count"] == 1
    assert consensus["consensus_market_count"] == 0
    assert all(not consensus["games"][0]["markets"][k]["consensus_available"]
               for k in MARKETS)

    from nba_market_consensus import selection_context
    ctx = selection_context(
        "JINGCAI_HANDICAP", 5.5, "HOME_COVER", 6.0, 224.0,
        12.0, 18.0, consensus["games"][0]["markets"])
    assert ctx["status"] == "AUXILIARY_CONSENSUS_UNAVAILABLE"
    assert ctx["consensus_line"] is None

    from nba_two_market_forecast import evaluate
    forecast = evaluate(board, {"games": [{
        "game_id": "728165", "model_status": "OK",
        "margin_mean_home_minus_away": 6.0, "total_mean": 226.0,
    }]}, comp)
    assert forecast["games"][0]["markets"]["SPREAD"]["company_count"] == 1
    assert forecast["games"][0]["markets"]["TOTAL"]["company_count"] == 1
    assert forecast["games"][0]["markets"]["SPREAD"]["line"] == 5.5
    print("OPTIONAL_007_ENRICHMENT_FAIL_OPEN_SELF_TEST_PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    collect = sub.add_parser("collect")
    collect.add_argument("--joined", required=True)
    collect.add_argument("--out", required=True)
    collect.add_argument("--analysis", required=True)
    collect.add_argument("--history-root")
    collect.add_argument("--status")
    collect.add_argument("--timeout", type=int, default=120)
    consensus = sub.add_parser("consensus")
    consensus.add_argument("--joined", required=True)
    consensus.add_argument("--top10", required=True)
    consensus.add_argument("--out", required=True)
    consensus.add_argument("--status")
    consensus.add_argument("--timeout", type=int, default=25)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.command == "collect":
        if args.timeout < 1:
            parser.error("--timeout must be positive")
        return run_collect(args)
    if args.command == "consensus":
        if args.timeout < 1:
            parser.error("--timeout must be positive")
        return run_consensus(args)
    return 0


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        self_test()
    else:
        raise SystemExit(main())
