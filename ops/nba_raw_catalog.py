#!/usr/bin/env python3
"""Verified, rebuildable monthly lookup catalog for long-lived NBA raw evidence.

Store this derived index on audit/nba-raw-search-catalog. Source is the separate
append-only archive branch. Every row retains manifest path and both SHA256s.
No source archive files are modified by this script.
"""
from __future__ import annotations
from collections import defaultdict
from datetime import datetime, timezone
import argparse
import hashlib
import json
from pathlib import Path
import sys

from nba_raw_vault import (audit, manifest_paths, open_manifest, validate_entry,
                           metadata, evidence_path)


def build(root, destination, day=None):
    root = Path(root)
    destination = Path(destination)
    verified = audit(root, day)
    grouped = defaultdict(list)
    for manifest in manifest_paths(root, day):
        doc, _ = open_manifest(root, manifest)
        game_date = manifest.split("/")[2]
        month = game_date[:7]
        for row in doc["files"]:
            raw = validate_entry(root, manifest, row)
            extra = metadata(raw, row.get("source_json_status"))
            record = {
                "game_date_beijing": game_date,
                "manifest": manifest,
                "source": row["relative_original_source"],
                "gzip": evidence_path(manifest, row),
                "run_id": doc.get("original_run_id"),
                "run_attempt": doc.get("original_run_attempt"),
                "workflow": doc.get("original_actions_workflow"),
                "archive_status": doc.get("status"),
                "missing_source_categories": doc.get("missing_required_source_categories", []),
                "source_json_status": row.get("source_json_status"),
                "source_snapshot_utc": row.get("source_snapshot_utc"),
                "source_sha256": row["source_sha256"],
                "gzip_sha256": row["gzip_sha256"],
                "source_bytes": row["source_bytes"],
                "compressed_bytes": row["compressed_bytes"],
                **extra,
            }
            grouped[month].append(record)
    if not grouped:
        raise ValueError("ARCHIVE_CATALOG_NO_DATA")
    for month, records in sorted(grouped.items()):
        out = destination / (month + ".jsonl")
        out.parent.mkdir(parents=True, exist_ok=True)
        content = "".join(json.dumps(r, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")) + "\n"
                          for r in sorted(records, key=lambda r: (
                              r["game_date_beijing"], r["manifest"], r["source"])))
        out.write_text(content, encoding="utf-8")
    summary = {
        "schema": "nba-raw-catalog-v1",
        "rebuilt_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_archive": "archive/nba-market-captures",
        "audited_manifests": verified["manifest_count"],
        "audited_gzip_files": verified["gzip_file_count"],
        "catalog_indexed_records": sum(map(len, grouped.values())),
        "months": sorted(grouped),
        "content_is_derived_and_rebuildable": True,
        "raw_archive_is_untouched": True,
        "index_files_sha256": {
            month: hashlib.sha256((destination / (month + ".jsonl")).read_bytes()).hexdigest()
            for month in sorted(grouped)
        },
    }
    (destination / "catalog-status.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8")
    return summary


def find(catalog, day=None, game=None, team=None, source=None, limit=100):
    catalog = Path(catalog)
    if not 1 <= limit <= 5000:
        raise ValueError("LIMIT_OUT_OF_RANGE")
    files = sorted(catalog.glob("????-??.jsonl"))
    count = 0
    for path in files:
        if day and path.stem != day[:7]:
            continue
        with path.open(encoding="utf-8") as stream:
            for line in stream:
                entry = json.loads(line)
                if day and entry["game_date_beijing"] != day: continue
                if source and source.casefold() not in entry["source"].casefold(): continue
                if game and game not in entry["game_ids"]: continue
                if team and not any(team.casefold() in n.casefold()
                                    for n in entry["teams"]): continue
                yield entry
                count += 1
                if count >= limit:
                    return


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="action", required=True)
    b = sub.add_parser("build")
    b.add_argument("--archive-root", required=True)
    b.add_argument("--catalog", required=True)
    b.add_argument("--day")
    q = sub.add_parser("query")
    q.add_argument("--catalog", required=True)
    q.add_argument("--day")
    q.add_argument("--game-id")
    q.add_argument("--team")
    q.add_argument("--source")
    q.add_argument("--limit", type=int, default=100)
    args = p.parse_args()
    if args.action == "build":
        print(json.dumps(build(args.archive_root, args.catalog, args.day),
                         ensure_ascii=False, indent=2))
    else:
        results = list(find(args.catalog, args.day, args.game_id,
                            args.team, args.source, args.limit))
        for row in results:
            print(json.dumps(row, ensure_ascii=False))
        print("INDEX_SEARCH_MATCHED", len(results), file=sys.stderr)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print("NBA_RAW_CATALOG_FAIL_CLOSED:", repr(exc), file=sys.stderr)
        sys.exit(2)
