#!/usr/bin/env python3
"""One-shot, read-only dated-007 NBA archive availability probe.

No request can retroactively create a PRETIP snapshot. A historical response
retrieved today is retrospective reference-only, regardless of the displayed
date. Checks robot policy, exact 007 NBA fixture IDs, and ID3 coverage with
bounded requests. Never crawls game detail pages, evades restrictions or
asserts these are historical timestamped prices.
"""
from __future__ import annotations
import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from xml.etree import ElementTree as ET
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from titan007_join_daily import identify,public_get
from titan007_join_beijing_verified import market_entries

DATES=("2023-11-15","2024-03-15","2025-01-15","2026-10-31","2026-11-01")
HOST="https://bf.titan007.com/"
USER_CONFIRMED_CROWN="3"


def urls(day):
    return (
        HOST+"nba_date.aspx?"+urlencode({"date":day,"h":"12","m":"00","s":"1"}),
        HOST+"nba_Oddsdata.aspx?"+urlencode({"date":day,"id":"3","h":"12","m":"00"})
    )


def probe(fetch=public_get,dates=DATES):
    results=[]
    for day in dates:
        row={
            "date_queried":day,"scoreboard_http":"NOT_ATTEMPTED",
            "crown_id3_http":"NOT_ATTEMPTED",
            "observed_at_utc":datetime.now(timezone.utc).isoformat(),
            "admission":"RETROSPECTIVE_ONLY_NEVER_HISTORICAL_PRETIP",
            "source_provider_quote_change_timestamp_verified":False,
            "source_id3_is_crown":True,
        }
        u0,u1=urls(day)
        matches={};prices={}
        try:
            matches,rej=identify(fetch(u0,limit=700000))
            row["scoreboard_http"]="PARSED"
            row["scoreboard_rejected"]=len(rej)
        except (OSError,RuntimeError,ValueError,ET.ParseError) as exc:
            row["scoreboard_http"]="FAILED_"+type(exc).__name__
        try:
            prices,rej=market_entries(fetch(u1,limit=350000))
            row["crown_id3_http"]="PARSED"
            row["crown_id3_rejected"]=dict(rej)
        except (OSError,RuntimeError,ValueError,ET.ParseError) as exc:
            row["crown_id3_http"]="FAILED_"+type(exc).__name__
        nba={gid:g for gid,g in matches.items()
             if g.get("league")=="NBA" and g.get("display_date")==day}
        exact={gid:p for gid,p in prices.items() if gid in nba}
        row.update({
            "scoreboard_records":len(matches),
            "requested_day_nba_fixtures":len(nba),
            "id3_all_leagues_records":len(prices),
            "id3_matched_nba_fixtures":len(exact),
            "id3_matched_spread_lines":sum(
                x.get("full_spread",{}).get("current",{}).get("line") is not None
                for x in exact.values()),
            "id3_matched_total_lines":sum(
                x.get("full_total",{}).get("current",{}).get("line") is not None
                for x in exact.values()),
            "sample_ids":sorted(exact)[:5],
        })
        results.append(row)
    return {
        "schema_version":"nba-007-retrospective-date-probe-v1",
        "purpose":"AVAILABILITY_ONLY_NO_HISTORIC_ASOF_FABRICATION",
        "date_checks":results,
        "observed_date_count":len(results),
        "historical_pretip_capture_rows_produced":0,
        "may_import_quotes_to_point_in_time_training":False,
        "production_changed":False,
    }


def self_test():
    data=probe(lambda url,limit: b"<bad>",dates=("2024-03-15",))
    assert len(data["date_checks"])==1
    row=data["date_checks"][0]
    assert row["id3_matched_nba_fixtures"]==0
    assert not data["may_import_quotes_to_point_in_time_training"]
    score,odds=urls("2024-03-15")
    assert "date=2024-03-15" in score and "date=2024-03-15" in odds
    assert "id=3" in odds
    print("NBA_007_OLD_DATE_PROBE_SELF_TEST_PASS")


if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--out", default="/tmp/nba-007-date-availability-probe.json")
    p.add_argument("--self-test",action="store_true")
    args=p.parse_args()
    if args.self_test:
        self_test()
    else:
        report=probe()
        Path(args.out).write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
        print("NBA_007_HISTORICAL_RETROSPECTIVE_DATE_PROBE",
              json.dumps(report,ensure_ascii=False))
