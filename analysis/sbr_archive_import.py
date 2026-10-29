#!/usr/bin/env python3
"""Fail-closed importer for locally saved Sportsbook Reviews Online NBA archives.

Research only. No network access, redistribution, or automatic training. SBR's
Open/Close cells each mix one total and one favorite-side spread across V/H rows.
The archive's ML is a *closing* American moneyline; it has no as-of timestamp.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import date, datetime
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re

COLUMNS = ("Date", "Rot", "VH", "Team", "Final", "Open", "Close", "ML")
TEAMS = {
    "atlanta": "ATL", "atlantahawks": "ATL", "boston": "BOS",
    "bostonceltics": "BOS", "brooklyn": "BKN", "brooklynnets": "BKN",
    "newjersey": "NJN", "newjerseynets": "NJN",
    "charlotte": "CHA", "charlottehornets": "CHA", "charlottebobcats": "CHA",
    "chicago": "CHI", "chicagobulls": "CHI",
    "cleveland": "CLE", "clevelandcavaliers": "CLE",
    "dallas": "DAL", "dallasmavericks": "DAL",
    "denver": "DEN", "denvernuggets": "DEN",
    "detroit": "DET", "detroitpistons": "DET",
    "goldenstate": "GSW", "goldenstatewarriors": "GSW",
    "houston": "HOU", "houstonrockets": "HOU",
    "indiana": "IND", "indianapacers": "IND",
    "laclippers": "LAC", "losangelesclippers": "LAC",
    "lalakers": "LAL", "losangeleslakers": "LAL",
    "memphis": "MEM", "memphisgrizzlies": "MEM",
    "miami": "MIA", "miamiheat": "MIA",
    "milwaukee": "MIL", "milwaukeebucks": "MIL",
    "minnesota": "MIN", "minnesotatimberwolves": "MIN",
    "neworleans": "NOP", "neworleanspelicans": "NOP",
    "neworleanshornets": "NOP",
    "newyork": "NYK", "newyorkknicks": "NYK",
    "oklahomacity": "OKC", "oklahomacitythunder": "OKC",
    "orlando": "ORL", "orlandomagic": "ORL",
    "philadelphia": "PHI", "philadelphia76ers": "PHI",
    "phoenix": "PHX", "phoenixsuns": "PHX",
    "portland": "POR", "portlandtrailblazers": "POR",
    "sacramento": "SAC", "sacramentokings": "SAC",
    "sanantonio": "SAS", "sanantoniospurs": "SAS",
    "seattle": "SEA", "seattlesupersonics": "SEA",
    "toronto": "TOR", "torontoraptors": "TOR",
    "utah": "UTA", "utahjazz": "UTA",
    "washington": "WAS", "washingtonwizards": "WAS",
}

def canonical_team(value):
    return TEAMS.get(re.sub(r"[^a-z0-9]", "", str(value).lower()))

def game_date(raw, season):
    start = int(season[:4])
    assert re.fullmatch(r"\d{4}-\d{2}", season)
    assert int(season[-2:]) == (start + 1) % 100
    if isinstance(raw, (date, datetime)):
        value = raw.date() if isinstance(raw, datetime) else raw
    else:
        s = str(raw).strip().split(".")[0]
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
            value = date.fromisoformat(s)
        elif re.fullmatch(r"\d{3,4}", s):
            month, day = int(s[:-2]), int(s[-2:])
            value = date(start if month >= 8 else start + 1, month, day)
        else:
            raise ValueError("INVALID_DATE_FORMAT")
    if not (date(start, 8, 1) <= value <= date(start + 1, 7, 31)):
        raise ValueError("DATE_OUTSIDE_SEASON")
    return value.isoformat()

def odds_to_probability(value):
    """Convert an American moneyline to raw implied win probability."""
    s = str(value).replace(",", "").strip().replace("−", "-")
    if not re.fullmatch(r"[+-]?\d+", s):
        raise ValueError("ML_MISSING_OR_NON_NUMERIC")
    ml = int(s)
    if ml == 0 or abs(ml) < 100 or abs(ml) > 100000:
        raise ValueError("ML_INVALID")
    return 100 / (ml + 100) if ml > 0 else -ml / (-ml + 100)

def classify_cell(value):
    s = str(value).strip().lower().replace(",", "")
    if s in ("pk", "pick", "pickem", "pick'em"):
        return "spread", 0.0
    try:
        x = float(s)
    except ValueError as exc:
        raise ValueError("LINE_MISSING_OR_INVALID") from exc
    if not (x >= 0):
        # SBR's documented convention gives the magnitude on the favorite row;
        # a signed source needs a separate, explicitly verified adapter.
        raise ValueError("SIGNED_LINE_UNVERIFIED")
    if x <= 50:
        return "spread", x
    if 140 <= x <= 330:
        return "total", x
    raise ValueError("LINE_OUT_OF_RANGE")

def read_pair(v, h, field):
    candidates = [(side, *classify_cell(record[field]))
                  for side, record in (("away", v), ("home", h))]
    spread = [(s, n) for s, kind, n in candidates if kind == "spread"]
    total = [n for _, kind, n in candidates if kind == "total"]
    if len(spread) != 1 or len(total) != 1:
        raise ValueError("SPREAD_TOTAL_STRUCTURE_INVALID")
    side, pts = spread[0]
    # Home handicap is NEGATIVE if HOME is the favorite.
    handicap = (-pts if side == "home" else pts)
    return handicap, total[0], side

class HTMLRows(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows = []
        self.row = None
        self.cell = None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.row = []
        elif tag in ("td", "th") and self.row is not None:
            self.cell = []

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self.row is not None and self.cell is not None:
            self.row.append(" ".join("".join(self.cell).split()))
            self.cell = None
        if tag == "tr" and self.row is not None:
            self.rows.append(self.row)
            self.row = None

def rows_from_grid(grid):
    header = None
    for line in grid:
        values = [str(x or "").strip() for x in line]
        if header is None:
            lookup = {s.lower().strip(): i for i, s in enumerate(values)}
            if all(name.lower() in lookup for name in COLUMNS):
                header = {name: lookup[name.lower()] for name in COLUMNS}
            continue
        if len(values) > max(header.values()):
            if values[header["VH"]].upper() in ("V", "H"):
                yield {name: values[i] for name, i in header.items()}
    if header is None:
        raise ValueError("NO_SBR_ARCHIVE_TABLE_SOFT_404")

def read_source(path):
    ext = path.suffix.lower()
    if ext == ".csv":
        with path.open(encoding="utf-8-sig", newline="") as f:
            yield from rows_from_grid(csv.reader(f))
    elif ext in (".html", ".htm"):
        parser = HTMLRows()
        parser.feed(path.read_text(encoding="utf-8-sig"))
        yield from rows_from_grid(parser.rows)
    elif ext == ".xlsx":
        try:
            from openpyxl import load_workbook
        except ImportError as exc:
            raise RuntimeError("Install openpyxl to read XLSX archives") from exc
        book = load_workbook(path, read_only=True, data_only=True)
        try:
            for sheet in book:
                try:
                    yield from rows_from_grid(sheet.iter_rows(values_only=True))
                    return
                except ValueError as exc:
                    if str(exc) != "NO_SBR_ARCHIVE_TABLE_SOFT_404":
                        raise
            raise ValueError("NO_SBR_ARCHIVE_TABLE_SOFT_404")
        finally:
            book.close()
    else:
        raise ValueError("UNSUPPORTED_FILE_EXTENSION")

def transform(records, season, source_sha):
    rows = list(records)
    accepted = []
    reject = Counter()
    seen = set()
    if len(rows) % 2:
        reject["ODD_NUMBER_OF_TEAM_ROWS"] += 1
    for i in range(0, len(rows) - 1, 2):
        v, h = rows[i:i + 2]
        try:
            if v["VH"].strip().upper() != "V" or h["VH"].strip().upper() != "H":
                raise ValueError("VISITOR_HOME_ROW_ORDER_INVALID")
            day = game_date(v["Date"], season)
            if day != game_date(h["Date"], season):
                raise ValueError("PAIR_DATE_MISMATCH")
            if not (v["Rot"].strip().isdigit() and h["Rot"].strip().isdigit()
                    and int(h["Rot"]) == int(v["Rot"]) + 1):
                raise ValueError("ROTATION_PAIR_MISMATCH")
            away, home = canonical_team(v["Team"]), canonical_team(h["Team"])
            if not away or not home or away == home:
                raise ValueError("UNKNOWN_OR_DUPLICATED_TEAM")
            key = (day, home, away)
            if key in seen:
                raise ValueError("DUPLICATE_GAME")
            seen.add(key)
            ap, hp = int(v["Final"]), int(h["Final"])
            if not (40 <= ap <= 200 and 40 <= hp <= 200):
                raise ValueError("SCORE_OUT_OF_RANGE")
            open_spread, open_total, _ = read_pair(v, h, "Open")
            close_spread, close_total, close_favorite = read_pair(v, h, "Close")
            away_q = odds_to_probability(v["ML"])
            home_q = odds_to_probability(h["ML"])
            vig = home_q + away_q - 1
            if not (-0.05 <= vig <= 0.30):
                raise ValueError("ML_OVERROUND_INVALID")
            # The closing spread must be on the closing ML favorite's row,
            # except near pick-em where the market's favorite can be ambiguous.
            if abs(close_spread) > 0.001 and abs(home_q - away_q) > 0.025:
                expected = "home" if home_q > away_q else "away"
                if expected != close_favorite:
                    raise ValueError("CLOSE_SPREAD_MONEYLINE_DIRECTION_CONFLICT")
            accepted.append({
                "source": "sportsbookreviewsonline_nba_archive",
                "source_sha256": source_sha, "season": season, "date": day,
                "home": home, "away": away,
                "home_points": hp, "away_points": ap,
                "home_margin": hp - ap, "final_total": hp + ap,
                "open_home_handicap": open_spread,
                "close_home_handicap": close_spread,
                "open_total": open_total, "close_total": close_total,
                "close_home_ml_implied_raw": home_q,
                "close_away_ml_implied_raw": away_q,
                "close_home_ml_no_vig": home_q / (home_q + away_q),
                "close_ml_overround": vig,
                "price_asof_timestamp": None,
                "quote_semantics": "ARCHIVE_OPEN_CLOSE_LABELS_WITHOUT_TIMESTAMPS",
                "model_use": "CLOSING_MARKET_BENCHMARK_ONLY",
                "training_eligible": False,
            })
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            reason = str(exc)
            reject[reason if reason.isupper() and len(reason) < 100 else "INVALID_PAIR"] += 1
    # Duplicates are poison: do not retain the first occurrence by accident.
    keycounts = Counter((x["date"], x["home"], x["away"]) for x in accepted)
    duplicated = {k for k, count in keycounts.items() if count > 1}
    if duplicated:
        accepted = [x for x in accepted if (x["date"], x["home"], x["away"]) not in duplicated]
        reject["DUPLICATE_GAME_BOTH_REJECTED"] += len(duplicated)
    return {
        "status": "RESEARCH_ONLY_NOT_TRAINING_APPROVED" if accepted else "NO_VALID_GAMES",
        "games": sorted(accepted, key=lambda r: (r["date"], r["home"], r["away"])),
        "audit": {
            "source_sha256": source_sha,
            "season": season,
            "input_team_rows": len(rows),
            "accepted_games": len(accepted),
            "rejected_pairs": dict(sorted(reject.items())),
            "no_precise_quote_timestamps": True,
            "no_live_source_access_required": True,
            "upstream_license_unverified": True,
            "sbr_archive_not_training_eligible": True,
        },
    }

def self_test():
    # Synthetic format based on verified SBR columns, NOT copied archive rows.
    head = "Date,Rot,VH,Team,Final,Open,Close,ML\n"
    sample = (
        "1022,501,V,NewOrleans,122,231.5,229.5,230\n"
        "1022,502,H,Toronto,130,6.5,6.5,-280\n"
        "1023,503,V,LALakers,102,3.5,224,150\n"
        "1023,504,H,LAClippers,112,227,3.5,-180\n"
        "1024,505,V,Milwaukee,117,230,230,-110\n"
        "1024,506,H,GoldenState,122,pk,pk,-110\n"
    )
    import io
    doc = transform(rows_from_grid(csv.reader(io.StringIO(head + sample))), "2019-20", "synthetic")
    assert doc["audit"]["accepted_games"] == 3, doc["audit"]
    x = {r["home"]: r for r in doc["games"]}
    assert x["TOR"]["open_home_handicap"] == -6.5
    # Opening favorite is the visitor, closing pick-em: do not infer from ML.
    assert x["GSW"]["close_home_handicap"] == 0
    assert x["LAC"]["open_home_handicap"] == 3.5
    assert x["LAC"]["close_home_handicap"] == -3.5
    assert x["TOR"]["date"] == "2019-10-22"
    assert abs(x["TOR"]["close_home_ml_no_vig"] - .715) < .02
    bad = (head + "1022,501,V,NewOrleans,122,231.5,229.5,230\n"
                  "1022,502,H,Toronto,130,6.5,6.5,200\n")
    invalid = transform(rows_from_grid(csv.reader(io.StringIO(bad))), "2019-20", "synthetic")
    assert invalid["audit"]["accepted_games"] == 0
    try:
        list(rows_from_grid([["Home", "About"], ["404", "Not found"]]))
        raise AssertionError("Soft-404 was accepted")
    except ValueError as exc:
        assert str(exc) == "NO_SBR_ARCHIVE_TABLE_SOFT_404"
    assert game_date("117", "2019-20") == "2020-01-17"
    print("SBR_ARCHIVE_IMPORT_SELF_TEST_PASS")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", type=Path)
    ap.add_argument("--season")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        self_test()
        return
    if not (args.input and args.season and args.out):
        ap.error("--input, --season and --out are required")
    if not re.fullmatch(r"20\d\d-\d\d", args.season):
        ap.error("season must look like 2019-20")
    content = args.input.read_bytes()
    report = transform(read_source(args.input), args.season, hashlib.sha256(content).hexdigest())
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": report["status"], **report["audit"]}, ensure_ascii=False))
    if report["status"] == "NO_VALID_GAMES":
        raise SystemExit(2)

if __name__ == "__main__":
    main()
