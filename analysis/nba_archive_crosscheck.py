#!/usr/bin/env python3
"""Cross-audit REAL historical NBA SBR odds against independent-repository score rows.

Downloads stay in process memory. No historical rows, prices, rejected samples or
archives are written to disk. This is NOT training admission or timestamp proof.
"""
from __future__ import annotations
from collections import Counter, defaultdict
from datetime import date
import csv
import hashlib
import io
import json
import math
from pathlib import Path
import sys
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sbr_archive_import import canonical_team, odds_to_probability, rows_from_grid, transform

ROOT = "https://raw.githubusercontent.com/"
LINE_SHEET = ROOT + "aaryanshah607/nba-line-sheet/main/nba_odds_clean.csv"
SBR_BASE = ROOT + "garfjohnson/Nba-Sports-Betting-Model/master/nba%20odds%20"
SEASONS = ("2015-16", "2016-17", "2017-18", "2018-19", "2019-20")
REQUIRED = {"Date", "Home", "Away", "OU", "Spread", "ML_Home", "ML_Away",
            "Points", "Win_Margin", "home_win"}

def bounded_fetch(url, limit=9_000_000):
    request = Request(url, headers={"User-Agent": "nba-history-cross-source-audit/1.0"})
    with urlopen(request, timeout=35) as r:
        if r.status != 200:
            raise ValueError("HTTP_NOT_200")
        data = r.read(limit + 1)
    if len(data) > limit:
        raise ValueError("TOO_LARGE")
    return data

def num(s):
    n = float(str(s).strip())
    if not math.isfinite(n):
        raise ValueError("NOT_FINITE")
    return n

def score_row(r):
    day = date.fromisoformat(r["Date"].strip()).isoformat()
    home, away = canonical_team(r["Home"]), canonical_team(r["Away"])
    if not home or not away or home == away:
        raise ValueError("INVALID_TEAM")
    total = num(r["Points"])
    margin = num(r["Win_Margin"])
    if total != int(total) or margin != int(margin) or (int(total + margin) % 2):
        raise ValueError("SCORE_PARITY")
    h, a = (total + margin)/2, (total-margin)/2
    if not 40 <= h <= 200 or not 40 <= a <= 200:
        raise ValueError("SCORE_RANGE")
    win = num(r["home_win"])
    if win not in (0, 1) or win != int(h > a):
        raise ValueError("WIN_MARGIN_CONFLICT")
    # If a market field is absent or malformed, admit neither its row nor its
    # score/odds union into a closing-price benchmark.
    t, sp = num(r["OU"]), num(r["Spread"])
    if not 140 <= t <= 330 or not 0 <= abs(sp) <= 50:
        raise ValueError("LINE_RANGE")
    def american(s):
        v = num(s)
        if v != int(v):
            raise ValueError("MONEYLINE_NONINTEGER")
        return odds_to_probability(str(int(v)))
    qh, qa = american(r["ML_Home"]), american(r["ML_Away"])
    if not -.05 <= qh+qa-1 <= .30:
        raise ValueError("ML_OVERROUND")
    return {"key": (day, home, away), "home_points": int(h),
            "away_points": int(a), "raw_home_probability": qh,
            "home_ml_no_vig": qh/(qh+qa)}

def line_sheet_audit(blob):
    body = blob.decode("utf-8-sig")
    rd = csv.DictReader(io.StringIO(body))
    if not REQUIRED.issubset(rd.fieldnames or ()):
        raise ValueError("LINE_SHEET_SCHEMA_CHANGED")
    keyed = defaultdict(list)
    rejected = Counter()
    rows = 0
    for row in rd:
        rows += 1
        try:
            val = score_row(row)
            keyed[val["key"]].append(val)
        except (ValueError, TypeError, OverflowError, KeyError) as e:
            reason = str(e)
            rejected[reason if reason.isupper() and len(reason)<60 else "INVALID_ROW"] += 1
    valid = {}
    duplicates = {"identical": 0, "conflicting": 0}
    for k, group in keyed.items():
        if len(group) == 1:
            valid[k] = group[0]
        else:
            if all(x == group[0] for x in group):
                duplicates["identical"] += len(group)-1
                # The second copy is not a new game.
                valid[k] = group[0]
            else:
                duplicates["conflicting"] += len(group)
                # Conflicting duplicates poison the entire key.
    return valid, {"source": LINE_SHEET, "sha256": hashlib.sha256(blob).hexdigest(),
                   "input_rows": rows, "valid_unique_games": len(valid),
                   "rejected_rows": dict(rejected), "duplicate_rows": duplicates,
                   "date_first": min((k[0] for k in valid), default=None),
                   "date_last": max((k[0] for k in valid), default=None)}

def sbr_season_audit(season, blob, reference):
    raw = blob.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(raw))
    if not {"VH", "Final", "Open", "Close", "ML", "Date", "Rot"}.issubset(reader.fieldnames or ()):
        raise ValueError("SBR_SCHEMA_CHANGED")
    side_counts = Counter()
    for row in reader:
        side_counts[str(row["VH"]).strip().upper()] += 1
    parsed = transform(rows_from_grid(csv.reader(io.StringIO(raw))),
                       season, hashlib.sha256(blob).hexdigest())
    audit = parsed["audit"]
    cross = Counter()
    seen_pairs = set()
    for g in parsed["games"]:
        k = (g["date"], g["home"], g["away"])
        if k in seen_pairs:
            cross["DUPLICATE_AFTER_PARSER"] += 1
            continue
        seen_pairs.add(k)
        ref = reference.get(k)
        if ref is None:
            cross["NO_UNIQUE_LINE_SHEET_PAIR"] += 1
        elif (ref["home_points"], ref["away_points"]) != (g["home_points"], g["away_points"]):
            cross["SCORE_CONFLICT_REJECT"] += 1
        else:
            cross["SCORE_MATCH"] += 1
            # Price comparisons are diagnostic, NOT an as-of-time match.
            if abs(ref["home_ml_no_vig"] - g["close_home_ml_no_vig"]) > .08:
                cross["CLOSING_ML_GAP_GT_8PP"] += 1
    counts = dict(sorted(cross.items()))
    matched = cross["SCORE_MATCH"]
    return {"season": season,
            "source_sha256": hashlib.sha256(blob).hexdigest(),
            "original_rows": sum(side_counts.values()),
            "original_side_values": dict(sorted(side_counts.items())),
            "ignored_non_vh_rows": sum(n for s,n in side_counts.items() if s not in ("V","H")),
            "parser_accepted_before_crosscheck": audit["accepted_games"],
            "parser_rejected_pairs": audit["rejected_pairs"],
            "score_crosscheck": counts,
            "score_matched_research_rows": matched,
            "training_eligible": False,
            "license_and_precise_price_timestamp_verified": False}

def self_test():
    good = {"Date":"2018-12-25", "Home":"Boston Celtics", "Away":"New York Knicks",
            "OU":"216.5", "Spread":"5.5", "ML_Home":"-200.0",
            "ML_Away":"170.0", "Points":"216", "Win_Margin":"10", "home_win":"1"}
    assert score_row(good)["home_points"] == 113
    assert score_row(good)["away_points"] == 103
    invalid = dict(good, Win_Margin="9")
    try:
        score_row(invalid)
        raise AssertionError("Score parity should have failed")
    except ValueError as e:
        assert str(e) == "SCORE_PARITY"
    conflict = dict(good, home_win="0")
    try:
        score_row(conflict)
        raise AssertionError("Home win should have failed")
    except ValueError as e:
        assert str(e) == "WIN_MARGIN_CONFLICT"
    # Contradictory duplicate cannot silently enter train/benchmark.
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(good))
    writer.writeheader()
    writer.writerow(good)
    writer.writerow(dict(good, Points="218"))
    items, audit = line_sheet_audit(buf.getvalue().encode())
    assert not items and audit["duplicate_rows"]["conflicting"] == 2
    print("NBA_CROSS_SOURCE_AUDIT_SELF_TEST_PASS")

def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--self-test", action="store_true")
    args = p.parse_args()
    if args.self_test:
        self_test()
        return
    line, baseline = line_sheet_audit(bounded_fetch(LINE_SHEET))
    print("LINE_SHEET_RECORD_AUDIT " + json.dumps(baseline, ensure_ascii=False, sort_keys=True))
    seasons = []
    for season in SEASONS:
        try:
            result = sbr_season_audit(season, bounded_fetch(SBR_BASE+season+".csv"), line)
        except Exception as e:
            result = {"season": season, "status": "REJECTED_FETCH_OR_AUDIT",
                      "error": type(e).__name__+":"+str(e)[:100],
                      "training_eligible": False}
        seasons.append(result)
        print("SBR_CROSS_SOURCE_AUDIT " + json.dumps(result, ensure_ascii=False, sort_keys=True))
    total = sum(x.get("score_matched_research_rows", 0) for x in seasons)
    verdict = {"source_count": len(seasons) + 1, "score_crosschecked_research_rows": total,
               "train_admitted": 0,
               "status": "RESEARCH_ONLY_SOURCE_RIGHTS_AND_PRICE_ASOF_NOT_VERIFIED",
               "no_raw_data_committed": True}
    print("HISTORICAL_ADMISSION_VERDICT " + json.dumps(verdict, ensure_ascii=False))
    if any("error" in x for x in seasons) or total == 0:
        raise SystemExit("INCOMPLETE_CROSSCHECK_NO_ADMISSION")

if __name__ == "__main__":
    main()
