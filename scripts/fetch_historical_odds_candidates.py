#!/usr/bin/env python3
"""Fetch approved public historical-odds candidates into a transient directory.

Raw files are never committed by this script. Each download is accompanied by SHA256 and
source metadata. Sources without a verified direct file URL are recorded as pending.
"""
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path
from urllib.request import Request, urlopen

SOURCES = {
    "hf_nba_odds_2026_27": {
        "url": "https://huggingface.co/datasets/minmaxxxer/nba-odds-2026-27/resolve/main/nba_2026_27_odds.csv",
        "license": "CC-BY-4.0",
        "status": "research_smoke_only",
    },
    "github_nba_line_sheet": {
        "url": "https://raw.githubusercontent.com/aaryanshah607/nba-line-sheet/main/nba_odds_clean.csv",
        "license": "MIT",
        "status": "closing_market_benchmark_only",
    },
}

def fetch(name, spec, out):
    target = out / f"{name}.dat"
    req = Request(spec["url"], headers={"User-Agent": "mcp-sports-hub-historical-audit/1.0"})
    with urlopen(req, timeout=30) as r:
        data = r.read()
    target.write_bytes(data)
    return {"id": name, **spec, "path": str(target), "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(), "downloaded": True}

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", default="tmp/historical-odds-candidates")
    p.add_argument("--self-test", action="store_true")
    a = p.parse_args()
    if a.self_test:
        assert set(SOURCES) == {"hf_nba_odds_2026_27", "github_nba_line_sheet"}
        print("HISTORICAL_ODDS_SOURCE_FETCH_SELF_TEST_PASS")
        return
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    rows = []
    for name, spec in SOURCES.items():
        try:
            rows.append(fetch(name, spec, out))
        except Exception as exc:
            rows.append({"id": name, **spec, "downloaded": False,
                         "error": f"{type(exc).__name__}: {str(exc)[:200]}"})
    report = out / "download_manifest.json"
    report.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(rows, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
