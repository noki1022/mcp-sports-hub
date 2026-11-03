#!/usr/bin/env python3
"""A verified NBA off-day is a valid zero-game result, not a pipeline outage.

Only the NBA league's own schedule confirmation may authorize this path.
A missing/failed source, stale 007 rows, or partial schedule cannot be
mistaken for a true off-day. No fabricated matches, quotes or predictions.
"""
from __future__ import annotations

import argparse
import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, date, timedelta
from html import escape
from pathlib import Path
from zoneinfo import ZoneInfo

from nba_official_beijing_schedule import (OFFICIAL_SCHEDULE, ESPN_SCHEDULE, fetch as fetch_league, parse_date as parse_league_utc)
from pushplus_mobile import send

BEIJING = ZoneInfo("Asia/Shanghai")
ACCEPTED = "API_ACCEPTED_NOT_DEVICE_CONFIRMED"


def espn_zero_game_confirmation(target: str, *, feeds: dict | None = None) -> None:
    """Fallback for NBA CDN HTTP 403: two US dates cover the entire Beijing day.

    Require independent dated ESPN responses for US(target-1) and US(target),
    plus neighboring NBA games to prove the source is active. Do not treat a
    network error, empty stale feed, malformed event, or partial response
    as a verified off-day.
    """
    from zoneinfo import ZoneInfo

    target_day = date.fromisoformat(target)
    et = ZoneInfo("America/New_York")
    dates = [target_day + timedelta(days=delta) for delta in (-2, -1, 0, 1)]
    active = {}
    for day in dates:
        key = day.strftime("%Y%m%d")
        if feeds is not None:
            if key not in feeds:
                raise RuntimeError("OFFDAY_ESPN_MISSING_DATED_RESPONSE")
            feed = feeds[key]
        else:
            url = ESPN_SCHEDULE + "?" + urllib.parse.urlencode({"dates": key, "limit": "100"})
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (compatible; NBA-OffdayDateAudit/1.0)",
                "Accept": "application/json",
            })
            with urllib.request.urlopen(req, timeout=18) as res:
                if res.status != 200:
                    raise RuntimeError("OFFDAY_ESPN_NON_200_RESPONSE")
                body = res.read(2000001)
                if len(body) > 2000000:
                    raise RuntimeError("OFFDAY_ESPN_RESPONSE_TOO_LARGE")
            feed = json.loads(body)
        if not isinstance(feed, dict):
            raise RuntimeError("OFFDAY_ESPN_MALFORMED_DATED_FEED")
        events, leagues = feed.get("events"), feed.get("leagues")
        if not isinstance(events, list) or len(events) >= 100:
            raise RuntimeError("OFFDAY_ESPN_EVENTS_MISSING_OR_TRUNCATED")
        if not isinstance(leagues, list) or not any(
            isinstance(x, dict) and
            (str(x.get("slug", "")).lower() == "nba" or
             str(x.get("abbreviation", "")).upper() == "NBA")
            for x in leagues
        ):
            raise RuntimeError("OFFDAY_ESPN_LEAGUE_IDENTITY_UNVERIFIED")
        for ev in events:
            if not isinstance(ev, dict) or not ev.get("id") or not ev.get("date"):
                raise RuntimeError("OFFDAY_ESPN_EVENT_IDENTITY_MISSING")
            utc = parse_league_utc(ev["date"])
            if utc.astimezone(et).date() != day:
                raise RuntimeError("OFFDAY_ESPN_WRONG_US_DATE_WINDOW")
            if utc.astimezone(BEIJING).date() == target_day:
                raise RuntimeError("OFFDAY_ESPN_CONFIRMS_GAMES_FOR_TARGET")
        active[key] = len(events)
    if active[dates[0].strftime("%Y%m%d")] == 0 or not (
        active[dates[2].strftime("%Y%m%d")] or
        active[dates[3].strftime("%Y%m%d")]
    ):
        raise RuntimeError("OFFDAY_ESPN_NEIGHBORING_GAME_DAYS_UNVERIFIED")
    print("OFFDAY_ESPN_UTC_DATE_CROSSCHECK_PASS", target,
          json.dumps(active, sort_keys=True), flush=True)


def league_zero_game_confirmation(target: str, league: dict | None = None) -> None:
    """Check the NBA league's real full-season fixture list, not a partial date API."""
    if league is None:
        try:
            league = fetch_league()
        except (OSError, ValueError, RuntimeError) as exc:
            print("OFFDAY_NBA_LEAGUE_CDN_UNAVAILABLE_ESPN_FALLBACK",
                  type(exc).__name__, flush=True)
            espn_zero_game_confirmation(target)
            return
    try:
        days = league["leagueSchedule"]["gameDates"]
        all_games = [game for day in days for game in day.get("games", [])]
        dated = [parse_league_utc(g["gameTimeUTC"]).astimezone(BEIJING).date() for g in all_games]
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError("OFFDAY_NBA_LEAGUE_SCHEDULE_INVALID") from exc
    if len(dated) < 100 or not (min(dated) < date.fromisoformat(target) < max(dated)):
        raise RuntimeError("OFFDAY_NBA_LEAGUE_SEASON_NOT_VERIFIED")
    if date.fromisoformat(target) in dated:
        raise RuntimeError("OFFDAY_NBA_LEAGUE_DISAGREES_ON_ZERO_GAME_DAY")


def verified_offday(board: dict, target: str, *, official_league: dict | None = None) -> bool:
    if board.get("requested_display_date") != target:
        raise RuntimeError("OFFDAY_TARGET_DATE_MISMATCH")
    try:
        captured = datetime.fromisoformat(str(board["captured_at_utc"]).replace("Z", "+00:00"))
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError("OFFDAY_CAPTURE_TIMESTAMP_INVALID") from exc
    if captured.tzinfo is None or captured.astimezone(BEIJING).date().isoformat() > target:
        raise RuntimeError("OFFDAY_CAPTURE_TIMESTAMP_OUT_OF_RANGE")
    fixtures = board.get("upcoming_nba_games")
    count = board.get("official_schedule_count")
    if not isinstance(fixtures, list) or not isinstance(count, int) or isinstance(count, bool):
        raise RuntimeError("OFFDAY_MISSING_OFFICIAL_SCHEDULE_EVIDENCE")
    if fixtures or count > 0:
        if count != len(fixtures):
            raise RuntimeError("OFFDAY_OFFICIAL_COUNT_MISMATCH")
        return False
    if count != 0:
        raise RuntimeError("OFFDAY_INVALID_OFFICIAL_COUNT")
    # Never infer an off-day from an empty ESPN window or unavailable feed.
    # Require full-season official NBA confirmation of the exact Beijing date.
    league_zero_game_confirmation(target, official_league)
    if (board.get("nba_cba_games") != [] or
            board.get("verified_fixture_ids_for_date") != 0 or
            board.get("markets_joined_for_date") != 0):
        raise RuntimeError("OFFDAY_CONTRADICTORY_MARKET_MATCHES")
    return True


def accepted_offday_marker(target: str, root: Path = Path(".")) -> bool:
    """Only an exact API-accepted, same-day zero-game noon marker can skip priority."""
    marker = root / "reports" / "pushplus-sent" / target / "1200.json"
    if not marker.is_file():
        return False
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return (isinstance(payload, dict)
            and payload.get("state") == ACCEPTED
            and payload.get("kind") == "VERIFIED_NBA_OFFDAY"
            and payload.get("target_date") == target
            and payload.get("slot") == "1200"
            and payload.get("games_considered") == 0)


def render(target: str) -> str:
    d = datetime.fromisoformat(target).strftime("%Y年%m月%d日")
    return ("<div style='max-width:520px;font-family:-apple-system,Arial;"
            "line-height:1.7;color:#243244;padding:12px'>"
            "<h3>北京时间 " + escape(d) + " NBA 球赛安排</h3>"
            "<p style='font-size:18px'><b>已核实：0 场比赛</b></p>"
            "<p>NBA 官方赛程确认该北京时间日期没有比赛。"
            "007 可能仍返回相邻日期的历史或未来场次，不能直接当作当天比赛。</p>"
            "<p>今日不生成竞彩、皇冠五玩法概率或盘口研判；"
            "这不是推送系统故障，也不代表漏掉比赛。</p>"
            "<p style='color:#64748b;font-size:12px'>"
            "12:00 赛程核验通知｜后续有比赛时继续按正常流程分析。</p></div>")


def self_test() -> None:
    league = {"leagueSchedule": {"gameDates": [
        {"games": [{"gameId": "1", "gameTimeUTC": "2026-10-30T23:00:00Z",
                    "homeTeam": {"teamTricode": "WAS"},
                    "awayTeam": {"teamTricode": "CHA"}}]},
        {"games": [{"gameId": str(i), "gameTimeUTC": "2026-11-01T23:00:00Z",
                    "homeTeam": {"teamTricode": "NYK"},
                    "awayTeam": {"teamTricode": "BOS"}} for i in range(2, 105)]},
        {"games": [{"gameId": "105", "gameTimeUTC": "2026-11-07T23:00:00Z",
                    "homeTeam": {"teamTricode": "UTA"},
                    "awayTeam": {"teamTricode": "DEN"}}]},
    ]}}
    board = {
        "requested_display_date": "2026-11-04",
        "captured_at_utc": "2026-11-03T04:00:25+00:00",
        "upcoming_nba_games": [],
        "official_schedule_count": 0,
        "official_schedule_source": [OFFICIAL_SCHEDULE],
        "nba_cba_games": [],
        "verified_fixture_ids_for_date": 0,
        "markets_joined_for_date": 0,
        "site_query_dates": {"2026-11-04": {"nba_rows": 15}},
    }
    assert verified_offday(board, "2026-11-04", official_league=league)
    assert "0 场比赛" in render("2026-11-04")
    assert not verified_offday({**board, "upcoming_nba_games": [{"nba_game_id": "1"}],
                                "official_schedule_count": 1}, "2026-11-04", official_league=league)
    for patch in (
        {"upcoming_nba_games": None},
        {"official_schedule_count": 1},
        {"verified_fixture_ids_for_date": 1},
        {"markets_joined_for_date": 1},
        {"nba_cba_games": [{"game_id": "123"}]},
    ):
        try:
            verified_offday({**board, **patch}, "2026-11-04", official_league=league)
        except RuntimeError:
            pass
        else:
            raise AssertionError("INVALID_OFFDAY_MUST_NOT_BE_ACCEPTED_" + repr(patch))
    try:
        verified_offday(board, "2026-11-05", official_league=league)
    except RuntimeError:
        pass
    else:
        raise AssertionError("WRONG_TARGET_MUST_NOT_BE_ACCEPTED")
    conflicting = json.loads(json.dumps(league))
    conflicting["leagueSchedule"]["gameDates"].append({"games": [{
        "gameId": "106", "gameTimeUTC": "2026-11-03T23:00:00Z",
        "homeTeam": {"teamTricode": "WAS"},
        "awayTeam": {"teamTricode": "CHA"},
    }]})
    try:
        verified_offday(board, "2026-11-04", official_league=conflicting)
    except RuntimeError:
        pass
    else:
        raise AssertionError("NBA_LEAGUE_CONFLICT_MUST_ABORT")
    # Simulate NBA CDN blocking GitHub runners (HTTP 403): ESPN fallback
    # needs both US dates plus real games on adjacent NBA calendar dates.
    def date_feed(events):
        return {"leagues": [{"slug": "nba", "abbreviation": "NBA"}],
                "events": events}
    def event(game_id, tip):
        return {"id": game_id, "date": tip}
    feeds = {
        "20261102": date_feed([event("es1", "2026-11-03T00:00:00Z")]),
        "20261103": date_feed([]),
        "20261104": date_feed([event("es2", "2026-11-05T00:00:00Z")]),
        "20261105": date_feed([event("es3", "2026-11-06T00:00:00Z")]),
    }
    espn_zero_game_confirmation("2026-11-04", feeds=feeds)
    conflicting_feeds = json.loads(json.dumps(feeds))
    conflicting_feeds["20261103"]["events"].append(event("bad", "2026-11-03T23:00:00Z"))
    for bad in (conflicting_feeds, {**feeds, "20261103": date_feed(None)},
                {**feeds, "20261102": date_feed([])}):
        try:
            espn_zero_game_confirmation("2026-11-04", feeds=bad)
        except (RuntimeError, TypeError):
            pass
        else:
            raise AssertionError("INVALID_OR_CONFLICTING_ESPN_OFFDAY_MUST_ABORT")
    from tempfile import TemporaryDirectory
    with TemporaryDirectory() as d:
        root = Path(d)
        marker = root / "reports/pushplus-sent/2026-11-04/1200.json"
        marker.parent.mkdir(parents=True)
        assert not accepted_offday_marker("2026-11-04", root)
        valid = {"state": ACCEPTED, "kind": "VERIFIED_NBA_OFFDAY",
                 "target_date": "2026-11-04", "slot": "1200",
                 "games_considered": 0}
        marker.write_text(json.dumps(valid))
        assert accepted_offday_marker("2026-11-04", root)
        assert not accepted_offday_marker("2026-11-05", root)
        marker.write_text(json.dumps({**valid, "games_considered": 1}))
        assert not accepted_offday_marker("2026-11-04", root)
    print("VERIFIED_NBA_OFFDAY_SELFTEST_PASS")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--joined")
    p.add_argument("--target")
    p.add_argument("--slot", default="1200")
    p.add_argument("--probe", action="store_true")
    p.add_argument("--send", action="store_true")
    p.add_argument("--status", default="nba_offday_pushplus_status.json")
    p.add_argument("--preview", default="nba_offday_pushplus_preview.html")
    p.add_argument("--marker-root", default="reports/pushplus-sent")
    p.add_argument("--self-test", action="store_true")
    args = p.parse_args()
    if args.self_test:
        self_test()
        return
    if not args.joined or not args.target or args.probe == args.send:
        p.error("--joined --target and exactly one of --probe / --send are required")
    board = json.loads(Path(args.joined).read_text(encoding="utf-8"))
    if not verified_offday(board, args.target):
        if args.probe:
            print("OFFDAY_NOT_APPLICABLE_OFFICIAL_FIXTURES_PRESENT")
            raise SystemExit(1)
        raise RuntimeError("OFFDAY_CANNOT_PUSH_WITH_OFFICIAL_FIXTURES")
    if args.probe:
        print("VERIFIED_ZERO_NBA_GAME_DAY", args.target,
              "UTC_SOURCE_CROSS_DATE_CONFIRMED", flush=True)
        return
    if args.slot != "1200":
        raise RuntimeError("OFFDAY_NOTIFICATION_IS_NOON_ONLY")
    if datetime.now(BEIJING).date().isoformat() > args.target:
        raise RuntimeError("OFFDAY_TARGET_EXPIRED")
    marker = Path(args.marker_root) / args.target / (args.slot + ".json")
    if marker.exists():
        existing = json.loads(marker.read_text(encoding="utf-8"))
        if existing.get("state") == ACCEPTED and existing.get("slot") == args.slot:
            print("OFFDAY_NOTIFICATION_ALREADY_ACCEPTED")
            return
        raise RuntimeError("OFFDAY_INVALID_EXISTING_DELIVERY_MARKER")
    html = render(args.target)
    Path(args.preview).write_text(html, encoding="utf-8")
    result = send({"title": "NBA赛程｜" + args.target + " 无比赛（12:00确认）",
                   "html": html}, os.environ.get("PUSHPLUS_TOKEN", ""))
    Path(args.status).write_text(json.dumps({
        "state": result["state"], "target_date": args.target, "slot": args.slot,
        "games": 0, "kind": "VERIFIED_NBA_OFFDAY",
        "message_id": result.get("message_id"),
    }, ensure_ascii=False) + "\n", encoding="utf-8")
    if result["state"] != ACCEPTED:
        raise RuntimeError("OFFDAY_PUSHPLUS_API_NOT_ACCEPTED")
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps({
        "state": ACCEPTED, "target_date": args.target, "slot": args.slot,
        "kind": "VERIFIED_NBA_OFFDAY", "games_considered": 0,
        "run_id": os.environ.get("GITHUB_RUN_ID"),
        "message_id": result.get("message_id"),
    }, ensure_ascii=False) + "\n", encoding="utf-8")
    print("VERIFIED_NBA_OFFDAY_PUSHPLUS_API_ACCEPTED_NOT_DEVICE_CONFIRMED",
          args.target, args.slot)


if __name__ == "__main__":
    main()
