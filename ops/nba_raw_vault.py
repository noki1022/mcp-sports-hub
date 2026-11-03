#!/usr/bin/env python3
"""Lossless, rebuildable index, integrity audit and exact-byte restore of NBA raw captures.

Read-only against reports/market-captures in archive/nba-market-captures. Never
edits source files, manifests or Git history. Only indexed evidence is shown;
missing categories and malformed original JSON remain visible in inventory.
"""
from __future__ import annotations

import argparse
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sys

PREFIX = "reports/market-captures"
SCHEMA = "nba-007-durable-market-evidence-v1"
HASH = re.compile(r"^[0-9a-f]{64}$")
DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MAX_MANIFEST = 12 * 1024 * 1024
MAX_RAW = 16 * 1024 * 1024
ID_KEYS = {"game_id", "match_id", "matchid", "event_id", "jc_number",
           "lottery_number", "jingcai_number", "jc_match_no", "serial_no"}
TEAM_KEYS = {"home_team", "away_team", "home", "away", "home_name",
             "away_name", "home_team_name", "away_team_name"}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def safe_rel(value):
    if not isinstance(value, str) or not value or len(value) > 500:
        raise ValueError("UNSAFE_RELATIVE_PATH")
    p = PurePosixPath(value)
    if p.is_absolute() or any(part in ("", ".", "..") or part.startswith(".")
                             for part in p.parts):
        raise ValueError("UNSAFE_RELATIVE_PATH:" + value[:80])
    return value


def within(root, path):
    rel = safe_rel(path)
    base = root.resolve(strict=True)
    target = root / rel
    if not target.resolve(strict=True).is_relative_to(base):
        raise ValueError("ARCHIVE_PATH_ESCAPES_ROOT")
    if any(p.is_symlink() for p in (target, *target.parents) if p != base):
        raise ValueError("SYMLINK_FORBIDDEN_IN_EVIDENCE")
    if not target.is_file():
        raise ValueError("EXPECTED_REGULAR_EVIDENCE_FILE:" + rel)
    return target


def manifest_paths(root, day=None):
    base = root / PREFIX
    if not base.is_dir() or base.is_symlink():
        raise ValueError("LONG_LIVED_ARCHIVE_ROOT_MISSING")
    if day and not DAY.fullmatch(day):
        raise ValueError("INVALID_BEIJING_GAME_DATE")
    scan = base / day if day else base
    if day and not scan.is_dir():
        return
    for path in sorted(scan.rglob("manifest.json")):
        rel = path.relative_to(root).as_posix()
        within(root, rel)
        yield rel


def open_manifest(root, rel):
    if not rel.startswith(PREFIX + "/") or not rel.endswith("/manifest.json"):
        raise ValueError("INVALID_CAPTURE_MANIFEST_PATH")
    path = within(root, rel)
    if path.stat().st_size > MAX_MANIFEST:
        raise ValueError("MANIFEST_TOO_LARGE")
    blob = path.read_bytes()
    doc = json.loads(blob)
    if doc.get("schema_version") != SCHEMA:
        raise ValueError("UNKNOWN_ARCHIVE_SCHEMA:" + rel)
    files = doc.get("files")
    if not isinstance(files, list) or not files or doc.get("file_count") != len(files):
        raise ValueError("MANIFEST_FILE_COUNT_INVALID:" + rel)
    seen = set()
    for row in files:
        src = safe_rel(row.get("relative_original_source"))
        gz = safe_rel(row.get("compressed_file"))
        if gz != "files/" + src + ".gz" or gz in seen:
            raise ValueError("SOURCE_PATH_COLLISION_OR_INCORRECT_GZIP:" + rel)
        seen.add(gz)
        for key in ("source_sha256", "gzip_sha256"):
            if not HASH.fullmatch(str(row.get(key))):
                raise ValueError("MISSING_OR_INVALID_HASH:" + rel)
        for key in ("source_bytes", "compressed_bytes"):
            if not isinstance(row.get(key), int) or not 0 < row[key] <= MAX_RAW:
                raise ValueError("INVALID_EVIDENCE_SIZE:" + rel)
    return doc, blob


def evidence_path(manifest, row):
    return manifest.rsplit("/", 1)[0] + "/" + row["compressed_file"]


def validate_entry(root, manifest, row):
    """Verify archived gzip bytes AND expanded original; fail closed."""
    path = within(root, evidence_path(manifest, row))
    if path.stat().st_size != row["compressed_bytes"]:
        raise ValueError("GZIP_SIZE_MISMATCH:" + str(path))
    compressed = path.read_bytes()
    if digest(compressed) != row["gzip_sha256"]:
        raise ValueError("GZIP_SHA256_MISMATCH:" + str(path))
    with gzip.open(path, "rb") as stream:
        data = stream.read(min(MAX_RAW + 1, row["source_bytes"] + 1))
        if len(data) != row["source_bytes"] or stream.read(1):
            raise ValueError("RAW_SIZE_MISMATCH_OR_OVERSIZE:" + str(path))
    if digest(data) != row["source_sha256"]:
        raise ValueError("RAW_SHA256_MISMATCH:" + str(path))
    return data


def metadata(data, status):
    if status != "VALID_JSON":
        return {"game_ids": [], "teams": []}
    try:
        obj = json.loads(data)
    except (ValueError, UnicodeDecodeError):
        return {"game_ids": [], "teams": []}
    ids, teams = set(), set()
    stack = [obj]
    visited = 0
    while stack and visited < 150000:
        item = stack.pop()
        visited += 1
        if isinstance(item, list):
            stack.extend(item[:10000])
        elif isinstance(item, dict):
            for k, v in item.items():
                key = str(k).lower()
                if key in ID_KEYS and isinstance(v, (int, str)):
                    if len(str(v)) <= 64:
                        ids.add(str(v))
                if key in TEAM_KEYS and isinstance(v, str) and 1 <= len(v) <= 80:
                    teams.add(v)
                if isinstance(v, (dict, list)):
                    stack.append(v)
    return {"game_ids": sorted(ids)[:1000], "teams": sorted(teams)[:1000]}


def records(root, day=None, source=None, game=None, verify=False):
    for manifest in manifest_paths(root, day):
        doc, _ = open_manifest(root, manifest)
        for row in doc["files"]:
            src = row["relative_original_source"]
            if source and source.casefold() not in src.casefold():
                continue
            data = validate_entry(root, manifest, row) if (verify or game) else None
            extra = metadata(data, row.get("source_json_status")) if game else {}
            if game and game not in extra["game_ids"]:
                continue
            yield {
                "game_date_beijing": manifest.split("/")[2],
                "manifest": manifest,
                "source": src,
                "gzip": evidence_path(manifest, row),
                "original_run_id": doc.get("original_run_id"),
                "original_run_attempt": doc.get("original_run_attempt"),
                "workflow": doc.get("original_actions_workflow"),
                "archive_status": doc.get("status"),
                "missing_source_categories": doc.get("missing_required_source_categories", []),
                "source_json_status": row.get("source_json_status"),
                "source_snapshot_utc": row.get("source_snapshot_utc"),
                "source_bytes": row["source_bytes"],
                "gzip_bytes": row["compressed_bytes"],
                "source_sha256": row["source_sha256"],
                "gzip_sha256": row["gzip_sha256"],
                **extra,
            }


def audit(root, day=None):
    count = Counter()
    total = 0
    for manifest in manifest_paths(root, day):
        doc, _ = open_manifest(root, manifest)
        count["manifests"] += 1
        if doc.get("missing_required_source_categories"):
            count["partial_manifests"] += 1
        expected = {evidence_path(manifest, row) for row in doc["files"]}
        folder = (root / manifest).parent / "files"
        actual = {p.relative_to(root).as_posix()
                  for p in folder.rglob("*.gz")} if folder.is_dir() else set()
        if expected != actual:
            raise ValueError("UNMANIFESTED_OR_MISSING_RAW_GZIP:" + manifest)
        for row in doc["files"]:
            validate_entry(root, manifest, row)
            count["gzip_files"] += 1
            total += row["source_bytes"]
            if row.get("source_json_status") != "VALID_JSON":
                count["non_json_or_invalid_json"] += 1
    if not count["manifests"]:
        raise ValueError("NO_DURABLE_MANIFESTS")
    return {"status": "SHA256_GZIP_RAW_ALL_VERIFIED",
            "manifest_count": count["manifests"],
            "gzip_file_count": count["gzip_files"],
            "raw_bytes_verified": total,
            "partial_manifests_not_silenced": count["partial_manifests"],
            "non_json_or_invalid_json_files": count["non_json_or_invalid_json"],
            "no_raw_data_mutated": True}


def restore(root, manifest, source, output):
    doc, _ = open_manifest(root, manifest)
    matching = [r for r in doc["files"] if r["relative_original_source"] == source]
    if len(matching) != 1:
        raise ValueError("RESTORE_REQUIRES_EXACT_MANIFEST_AND_SOURCE")
    raw = validate_entry(root, manifest, matching[0])
    target = Path(output)
    if not target.parent.is_dir():
        raise ValueError("RESTORE_DESTINATION_PARENT_MISSING")
    with target.open("xb") as stream:
        stream.write(raw)
    if digest(target.read_bytes()) != matching[0]["source_sha256"]:
        target.unlink()
        raise ValueError("RESTORE_VERIFY_FAILED")
    return {"restored": str(target), "sha256": digest(raw),
            "bytes": len(raw), "source": source, "manifest": manifest}


def selftest():
    import tempfile
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        relative = PREFIX + "/2026-11-03/original-run-123/attempt-1/manifest.json"
        parent = root / relative
        parent.parent.mkdir(parents=True)
        raw = b'{"games":[{"game_id":"728298","home_team":"A","away_team":"B"}]}'
        gz = gzip.compress(raw, mtime=0)
        src = "nba_jingcai_three_market.json"
        row = {"relative_original_source": src, "compressed_file": "files/" + src + ".gz",
               "source_sha256": digest(raw), "gzip_sha256": digest(gz),
               "source_bytes": len(raw), "compressed_bytes": len(gz),
               "source_json_status": "VALID_JSON"}
        f = parent.parent / row["compressed_file"]
        f.parent.mkdir()
        f.write_bytes(gz)
        parent.write_text(json.dumps({"schema_version": SCHEMA, "file_count": 1,
                                      "files": [row], "status": "CAPTURE_ARCHIVED"}))
        assert audit(root)["gzip_file_count"] == 1
        found = list(records(root, day="2026-11-03", game="728298"))
        assert len(found) == 1 and found[0]["source"] == src
        output = root / "restored.json"
        assert restore(root, relative, src, output)["sha256"] == digest(raw)
        assert output.read_bytes() == raw
        try:
            restore(root, relative, src, output)
        except FileExistsError:
            pass
        else:
            raise AssertionError("RESTORE_OVERWRITE_NOT_BLOCKED")
        f.write_bytes(gz[:-1] + bytes([gz[-1] ^ 1]))
        try:
            audit(root)
        except ValueError:
            pass
        else:
            raise AssertionError("TAMPER_UNDETECTED")
        try:
            safe_rel("../escape")
        except ValueError:
            pass
        else:
            raise AssertionError("TRAVERSAL_UNDETECTED")
    print("NBA_RAW_VAULT_SEARCH_AUDIT_RESTORE_SELFTEST_PASSED")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--archive-root", default=".")
    sub = p.add_subparsers(dest="command", required=True)
    a = sub.add_parser("audit")
    a.add_argument("--day")
    s = sub.add_parser("search")
    s.add_argument("--day")
    s.add_argument("--source", help="case-insensitive original path substring")
    s.add_argument("--game-id", help="exact match of game_id/event_id/JC number found in JSON")
    s.add_argument("--verify", action="store_true")
    s.add_argument("--limit", type=int, default=100)
    s.add_argument("--output", help="optional JSONL file; never overwrite")
    r = sub.add_parser("restore")
    r.add_argument("--manifest", required=True)
    r.add_argument("--source", required=True)
    r.add_argument("--output", required=True)
    sub.add_parser("selftest")
    args = p.parse_args()
    if args.command == "selftest":
        selftest()
        return
    root = Path(args.archive_root)
    if args.command == "audit":
        print(json.dumps(audit(root, args.day), ensure_ascii=False, indent=2))
    elif args.command == "restore":
        print(json.dumps(restore(root, args.manifest, args.source, args.output),
                         ensure_ascii=False, indent=2))
    else:
        if not 1 <= args.limit <= 10000:
            raise ValueError("INVALID_SEARCH_LIMIT")
        chosen = list(records(root, args.day, args.source, args.game_id, args.verify))
        if not chosen:
            print("NO_MATCHING_ARCHIVED_EVIDENCE", file=sys.stderr)
            return
        lines = [json.dumps(r, ensure_ascii=False, sort_keys=True) for r in chosen[:args.limit]]
        if args.output:
            with Path(args.output).open("x", encoding="utf-8") as stream:
                stream.write("\n".join(lines) + "\n")
        for line in lines:
            print(line)
        print("SEARCH_MATCHES", len(chosen), "DISPLAYED", len(lines), file=sys.stderr)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, TypeError, EOFError) as exc:
        print("NBA_RAW_VAULT_FAIL_CLOSED:", repr(exc), file=sys.stderr)
        sys.exit(2)
