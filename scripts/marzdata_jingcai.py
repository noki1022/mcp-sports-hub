#!/usr/bin/env python3
"""Optional, authorized Marzdata lottery basketball feed.

Source: https://doc.marzdata.cn/api-252526119 (sport_id=201).
This is NOT an official Chinese Sports Lottery feed. Until independently
verified the meaning/order of the comma-separated selection slots, show raw
quotes for audit only, never infer a betting direction or return.
No request is made without BOTH API credentials.
"""
from __future__ import annotations
import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

ENDPOINT = "https://api.marzdata.cn/lot/api/v3/csl/list/jc/odds"
MARKETS = {"WIN_LOSE": "sf", "HANDICAP_WIN_LOSE": "rf", "TOTAL": "dxf"}
ALIASES = {
    "老鹰": "ATL", "凯尔特人": "BOS", "篮网": "BKN", "黄蜂": "CHA",
    "公牛": "CHI", "骑士": "CLE", "独行侠": "DAL", "小牛": "DAL",
    "掘金": "DEN", "活塞": "DET", "勇士": "GSW", "火箭": "HOU",
    "步行者": "IND", "快船": "LAC", "湖人": "LAL", "灰熊": "MEM",
    "热火": "MIA", "雄鹿": "MIL", "森林狼": "MIN", "鹈鹕": "NOP",
    "尼克斯": "NYK", "雷霆": "OKC", "魔术": "ORL", "76人": "PHI",
    "太阳": "PHX", "开拓者": "POR", "国王": "SAC", "马刺": "SAS",
    "猛龙": "TOR", "爵士": "UTA", "奇才": "WAS",
}

def team_code(value):
    name = str(value or "").replace(" ", "")
    if len(name) in (2, 3) and name.upper() in set(ALIASES.values()):
        return name.upper()
    matches = {code for alias, code in ALIASES.items() if alias in name}
    return next(iter(matches)) if len(matches) == 1 else None

def read_response(url, headers):
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=10) as response:
        if response.status != 200:
            raise RuntimeError("NON_200_RESPONSE")
        return json.loads(response.read(600000).decode("utf-8"))

def get_quotes(target_date, app_id, app_secret, fetcher=None):
    """Retrieve only an authorized, bounded portion; flag pagination gaps."""
    fetcher = fetcher or read_response
    day = datetime.fromisoformat(target_date).replace(tzinfo=ZoneInfo("Asia/Shanghai"))
    earliest = int((day - timedelta(hours=12)).timestamp())
    headers = {"app_id": app_id, "app_secret": app_secret,
               "Accept": "application/json", "User-Agent": "NBA-DataAudit/1.0"}
    rows, exhausted, calls = [], False, 0
    for page in range(1, 5):  # 4 requests < documented 5/min suggestion
        query = urllib.parse.urlencode({
            "sport_id": 201, "start_time": earliest,
            "page": page, "per_page": 200
        })
        payload = fetcher(ENDPOINT + "?" + query, headers)
        calls += 1
        if not isinstance(payload, dict) or str(payload.get("code")) != "0":
            raise RuntimeError("MARZDATA_API_NOT_SUCCESS")
        data = payload.get("data")
        if not isinstance(data, dict) or not isinstance(data.get("list"), list):
            raise RuntimeError("MARZDATA_SCHEMA_UNEXPECTED")
        batch = data["list"]
        rows.extend(batch)
        if not batch or len(batch) < 200:
            exhausted = True
            break
        total = data.get("total")
        if isinstance(total, int) and page * 200 >= total:
            exhausted = True
            break
    return rows, {"calls": calls, "page_exhausted": exhausted,
                  "rows_retrieved": len(rows),
                  "pagination_complete": exhausted}

def split_odds(value, expected):
    pieces = str(value or "").split(",")
    if len(pieces) != expected:
        return None
    try:
        nums = [float(x.strip()) for x in pieces]
    except (ValueError, OverflowError):
        return None
    import math
    if not all(math.isfinite(x) for x in nums):
        return None
    first = nums[0] if expected == 3 else None
    if expected == 3 and not (-60 <= first <= 350):
        return None
    prices = nums[1:] if expected == 3 else nums
    if any(not (1.0 < x < 1000) for x in prices):
        return None
    return nums

def select_row(game, rows):
    """Fail closed on wrong league, lineup, time-zone mismatch or duplicate."""
    gh, ga = team_code(game.get("home_team")), team_code(game.get("away_team"))
    if not gh or not ga:
        return None, "UNRECOGNIZED_TEAM"
    try:
        tip = datetime.fromisoformat(game["start_time_beijing"]).timestamp()
    except (KeyError, ValueError, TypeError):
        return None, "TIPOFF_MISSING"
    candidates = []
    for row in rows:
        if not isinstance(row, dict) or str(row.get("sport_id")) != "201":
            continue
        comp = str(row.get("comp") or "") + str(row.get("short_comp") or "")
        if not any(k in comp for k in ("NBA", "美职篮", "美国职业篮球")):
            continue
        rh = team_code(row.get("home") or row.get("short_home"))
        ra = team_code(row.get("away") or row.get("short_away"))
        if rh != gh or ra != ga:
            continue
        try:
            when = float(row.get("match_time"))
        except (ValueError, TypeError):
            continue
        if abs(when - tip) <= 20 * 60:
            candidates.append(row)
    if len(candidates) != 1:
        return None, ("NO_EXACT_TIME_TEAM_MATCH" if not candidates else "AMBIGUOUS_MATCH")
    return candidates[0], "MATCHED"

def enrich(board, audit, *, app_id=None, app_secret=None, fetcher=None,
           slot_order_confirmed=None):
    """Shadow-feed overlay on the 007 audit; never substitute bookmaker prices."""
    app_id = app_id if app_id is not None else os.getenv("MARZDATA_APP_ID", "")
    app_secret = app_secret if app_secret is not None else os.getenv("MARZDATA_APP_SECRET", "")
    approved_order = (slot_order_confirmed if slot_order_confirmed is not None
                      else os.getenv("MARZDATA_SLOT_ORDER_CONFIRMED") == "1")
    status = {"provider": "MARZDATA_THIRD_PARTY_NOT_OFFICIAL",
              "documentation": "https://doc.marzdata.cn/api-252526119",
              "credentials_present": bool(app_id and app_secret),
              "status": "NOT_CONFIGURED", "matched_games": 0, "three_market_games": 0,
              "slot_order_confirmed": bool(approved_order)}
    audit["alternate_provider_status"] = status
    if not (app_id and app_secret):
        return audit
    try:
        rows, paging = get_quotes(board["requested_display_date"], app_id, app_secret, fetcher)
    except (OSError, ValueError, KeyError, RuntimeError, TypeError) as exc:
        status["status"] = "FETCH_FAILED"
        status["reason"] = type(exc).__name__  # never log credentials or URL header
        return audit
    status.update(paging)
    status["status"] = "FETCHED_UNVERIFIED"
    stamp = datetime.now(timezone.utc).isoformat()
    for game in audit.get("games", []):
        source_game = next((g for g in board.get("nba_cba_games", [])
                            if str(g.get("game_id")) == str(game["game_id"])), None)
        if not source_game:
            continue
        candidate, reason = select_row(source_game, rows)
        if candidate is None:
            game["marzdata_match_status"] = reason
            continue
        status["matched_games"] += 1
        game["marzdata_match_status"] = "EXACT_TEAM_AND_TIPOFF_MATCH"
        complete = True
        for key, field in MARKETS.items():
            numbers = split_odds(candidate.get(field), 2 if field == "sf" else 3)
            if numbers is None:
                complete = False
                game["markets"][key]["reason"] = "MARZDATA_FIELD_MISSING_OR_INVALID"
                continue
            record = game["markets"][key]
            record.update({
                "status": "VERIFIED" if approved_order else "RAW_QUOTE_SLOT_ORDER_UNVERIFIED",
                "reason": ("THIRD_PARTY_MATCHED_SLOTS_CONFIRMED" if approved_order
                           else "SOURCE_DOCS_DO_NOT_EXPLICITLY_DEFINE_SELECTION_ORDER"),
                "source": "MARZDATA_AUTHORIZED_THIRD_PARTY",
                "lot_id": candidate.get("lot_id"),
                "issue_num": candidate.get("issue_num"),
                "observed_at_utc": stamp,
                "sell_status_uninterpreted": candidate.get("sell_status"),
                "raw_slots": numbers,
                "line": numbers[0] if len(numbers) == 3 else None
            })
            if approved_order:
                if key == "TOTAL":
                    record["over_odds"], record["under_odds"] = numbers[1:]
                elif key == "HANDICAP_WIN_LOSE":
                    record["home_odds"], record["away_odds"] = numbers[1:]
                else:
                    record["home_odds"], record["away_odds"] = numbers
        if complete:
            status["three_market_games"] += 1
    if status["three_market_games"]:
        status["status"] = ("MATCHED_QUOTES_VERIFIED" if approved_order
                             else "MATCHED_QUOTES_ORDER_UNVERIFIED")
    audit["verified_games_with_all_three"] = (status["three_market_games"] if approved_order else 0)
    audit["status"] = ("THIRD_PARTY_JINGCAI_QUOTE_VERIFIED_NOT_OFFICIAL"
                       if approved_order and status["three_market_games"]
                       else "THIRD_PARTY_QUOTES_NEED_SLOT_VERIFICATION"
                       if status["three_market_games"] else
                       "JINGCAI_PRICES_UNAVAILABLE_DO_NOT_USE_COMMERCIAL_ODDS_AS_PROXY")
    # A quote alone never authorizes fusion / returns; requires separate gates.
    audit["model_fusion_enabled"] = False
    audit["jingcai_return_calculation_enabled"] = False
    return audit

def self_test():
    board = {"requested_display_date": "2024-11-28",
             "nba_cba_games": [{
                 "league": "NBA", "game_id": "test",
                 "home_team": "克利夫兰骑士", "away_team": "亚特兰大老鹰",
                 "start_time_beijing": "2024-11-28T08:00:00+08:00"}]}
    empty = {"games": [{
        "game_id": "test", "markets": {m: {"status": "NO_VERIFIED_JINGCAI_ODDS"}
                                     for m in MARKETS}}]}
    def fixture(url, headers):
        assert "sport_id=201" in url
        assert headers["app_id"] == "test" and headers["app_secret"] == "test"
        return {"code": 0, "data": {"total": 1, "list": [{
            "lot_id": 11537, "sport_id": 201,
            "comp": "美国职业篮球联盟", "home": "克利夫兰骑士",
            "away": "亚特兰大老鹰", "match_time": 1732752000,
            "sf": "1.04,4.60", "rf": "-11.5,1.76,1.64",
            "dxf": "240.5,1.66,1.74"}]}}
    import copy
    d = enrich(board, copy.deepcopy(empty), app_id="", app_secret="")
    assert d["alternate_provider_status"]["status"] == "NOT_CONFIGURED"
    d = enrich(board, copy.deepcopy(empty), app_id="test", app_secret="test", fetcher=fixture)
    assert d["alternate_provider_status"]["three_market_games"] == 1
    assert d["verified_games_with_all_three"] == 0
    assert d["games"][0]["markets"]["TOTAL"]["raw_slots"] == [240.5, 1.66, 1.74]
    assert d["games"][0]["markets"]["WIN_LOSE"]["status"] != "VERIFIED"
    d = enrich(board, copy.deepcopy(empty), app_id="test", app_secret="test",
               fetcher=fixture, slot_order_confirmed=True)
    assert d["verified_games_with_all_three"] == 1
    assert d["games"][0]["markets"]["TOTAL"]["under_odds"] == 1.74
    assert select_row({**board["nba_cba_games"][0], "away_team": "波士顿凯尔特人"},
                      fixture("https://test/?sport_id=201", {"app_id": "test", "app_secret": "test"})["data"]["list"])[0] is None
    print("MARZDATA_JINGCAI_SHADOW_FEED_SELF_TEST_PASS")

if __name__ == "__main__":
    self_test()
