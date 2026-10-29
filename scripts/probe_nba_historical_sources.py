#!/usr/bin/env python3
"""Ephemeral real NBA archive source audit. Never writes raw datasets into git."""
import csv
import hashlib
import io
import json
import re
from pathlib import Path
from urllib.request import Request, urlopen

CANDIDATES = {
    "line_sheet": "https://raw.githubusercontent.com/aaryanshah607/nba-line-sheet/main/nba_odds_clean.csv",
    **{
        "sbr_" + year: "https://raw.githubusercontent.com/garfjohnson/Nba-Sports-Betting-Model/master/nba%20odds%20" + year + ".csv"
        for year in ("2015-16", "2016-17", "2017-18", "2018-19", "2019-20")
    },
}

def download(url, limit=8500000):
    req = Request(url, headers={"User-Agent": "nba-research-integrity-audit/1.0"})
    with urlopen(req, timeout=35) as response:
        body = response.read(limit + 1)
        if len(body) > limit:
            raise ValueError("SOURCE_EXCEEDS_BOUNDED_DOWNLOAD")
        if response.status != 200:
            raise ValueError("HTTP_STATUS_NOT_200")
    return body

def profile(name, url):
    body = download(url)
    raw = body.decode("utf-8-sig")
    parsed = csv.reader(io.StringIO(raw))
    header = next(parsed)
    sample = []
    counts = {"rows": 0, "bad_column_count": 0, "empty_rows": 0}
    for row in parsed:
        if not any(x.strip() for x in row):
            counts["empty_rows"] += 1
            continue
        counts["rows"] += 1
        if len(row) != len(header):
            counts["bad_column_count"] += 1
        if len(sample) < 2:
            sample.append(row[:min(len(row), 16)])
    return {"source": name, "url": url, "sha256": hashlib.sha256(body).hexdigest(),
            "size_bytes": len(body), "header": header, "sample_rows": sample,
            "counts": counts, "downloaded_for_audit_only": True,
            "train_eligible": False, "raw_files_committed": False}

def main():
    inventory = []
    for name, url in CANDIDATES.items():
        try:
            result = profile(name, url)
        except Exception as e:
            result = {"source": name, "url": url, "status": "REJECTED_FETCH_OR_STRUCTURE",
                      "reason": type(e).__name__ + ": " + str(e)[:120],
                      "train_eligible": False}
        inventory.append(result)
        print("SOURCE_PROBE " + json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    out = Path("/tmp/nba_historical_probe.json")
    out.write_text(json.dumps({"results": inventory}, indent=2), encoding="utf-8")
    print("NO_ARCHIVE_DATA_WRITTEN_TO_REPOSITORY")
    if not any(r.get("counts", {}).get("rows", 0) > 100 for r in inventory):
        raise SystemExit("NO_USEFUL_SOURCES_AUDITED")

if __name__ == "__main__":
    main()
