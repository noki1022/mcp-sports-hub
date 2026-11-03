#!/usr/bin/env python3
"""Append-once, byte-faithful gzip archive of original NBA 007 market captures.

No retrieval, inference, PushPlus, result settlement or secrets. The input is
the *completed* original GitHub Action's artifact, including an action that
failed after actually collecting data; the output goes to a separate Git
branch. The original source JSON is never reinterpreted or rewritten.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
import re
import sys

SCHEMA = "nba-007-durable-market-evidence-v1"
WORKFLOWS = {
    "Titan007 scheduled full-board NBA analysis and PushPlus delivery":
        "titan007-three-analysis-",
    "NBA PRIORITY 21:30 Beijing pre-cutoff report": "nba-priority-2130-",
    "NBA PRIORITY 06:30 Beijing morning full report": "nba-priority-0630-",
    "Titan007 NBA/CBA final one-hour report": "titan007-final-window-",
}
MAX_FILES = 750
MAX_ONE_FILE = 12 * 1024 * 1024
MAX_TOTAL = 85 * 1024 * 1024
DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
IDENT = re.compile(r"^[1-9]\d{0,19}$")
SAFE_FILE = re.compile(r"^[a-zA-Z0-9_.-]+\.(?:json|csv)$")
SENSITIVE = ("api_key", "apikey", "access_token", "pushplus_token",
             "authorization", "password", "private_key", "client_secret",
             "cookie", "secret_key")
# The entire real source JSON is saved. These are the game-data producers
# only, never messages/push receipts or unknown generated files.
TOP_PREFIXES = ("nba_", "titan007_", "market_value_policy")
SPECIAL = ("reports/hourly/", "reports/top10/", "reports/hourly-reviews/",
           "reports/five-market-intraday/", "reports/two-market-intraday/",
           "reports/overnight-cohorts/", "reports/noon-cohorts/")
SKIP_NAMES = {
    "pushplus_status.json", "nba_priority_pushplus_status.json",
    "schedule_fallback_status.json", "pushplus_mobile_preview.html",
}
BOARD_NAMES = {"titan007_three_joined.json", "titan007_priority_joined.json",
               "titan007_joined_today.json", "titan007_final_window.json"}
JC_NAME = "nba_jingcai_three_market.json"
BOOK_NAME = "nba_top10_companies.json"
CONSENSUS_NAME = "nba_market_consensus.json"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_relative(relative: str) -> bool:
    p = PurePosixPath(relative)
    if not relative or p.is_absolute() or ".." in p.parts:
        return False
    if any(x.startswith(".") for x in p.parts):
        return False
    if len(relative) > 300:
        return False
    if p.name in SKIP_NAMES or not SAFE_FILE.fullmatch(p.name):
        return False
    return (p.name.startswith(TOP_PREFIXES)
            or any(relative.startswith(prefix) for prefix in SPECIAL))


def secret_key(obj) -> str | None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            name = str(k).lower().replace("-", "_")
            if any(s in name for s in SENSITIVE):
                return str(k)
            hit = secret_key(v)
            if hit is not None:
                return hit
    elif isinstance(obj, list):
        for v in obj:
            hit = secret_key(v)
            if hit is not None:
                return hit
    return None


def snapshot_time(obj):
    if not isinstance(obj, dict):
        return None
    for k in ("collection_completed_at_utc", "captured_at_utc",
              "board_capture_utc", "source_capture_utc"):
        if isinstance(obj.get(k), str):
            return obj[k]
    child = obj.get("jc_007_public_odds_shadow")
    if isinstance(child, dict) and isinstance(child.get("captured_at_utc"), str):
        return child["captured_at_utc"]
    return None


def read_source(path: Path) -> tuple[bytes, dict | None]:
    if path.is_symlink() or not path.is_file():
        raise ValueError("UNTRUSTED_SOURCE_SYMLINK_OR_NOT_FILE")
    if path.stat().st_size > MAX_ONE_FILE:
        raise ValueError("SOURCE_FILE_EXCEEDS_MAX_BYTES")
    raw = path.read_bytes()
    obj = None
    if path.suffix == ".json":
        try:
            obj = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            # Never discard uniquely timestamped evidence because a prior
            # producer accidentally appended two JSON documents. Preserve
            # ORIGINAL BYTES exactly, but flag that source as malformed:
            # it is NOT an approved parsed training sample.
            low = raw.lower()
            for name in SENSITIVE:
                needle = name.encode("ascii")
                if re.search(rb'"' + re.escape(needle) + rb'"\s*:', low):
                    raise ValueError("POSSIBLE_SECRET_IN_MALFORMED_JSON:"+name)
            print("MALFORMED_ORIGINAL_JSON_PRESERVED_NOT_TRAINING_APPROVED",
                  path.name,type(exc).__name__,str(exc)[:100])
    if obj is not None:
        unsafe = secret_key(obj)
        if unsafe:
            raise ValueError("SECRET_FIELD_IN_CAPTURED_DATA:" + unsafe)
    return raw, obj


def add_file(root: Path, source: Path, logical: str, output: Path, entries: list):
    if not safe_relative(logical):
        return False
    data, obj = read_source(source)
    if not data:
        raise ValueError("ZERO_BYTE_CAPTURE_" + logical)
    zipped = gzip.compress(data, compresslevel=9, mtime=0)
    name = logical + ".gz"
    target = output / "files" / name
    if target.exists():
        raise ValueError("NEVER_OVERWRITE_RAW_007_SOURCE_FILE:" + logical)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(zipped)
    entry = {
        "relative_original_source": logical,
        "compressed_file": "files/" + name,
        "source_sha256": sha(data),
        "gzip_sha256": sha(zipped),
        "source_bytes": len(data),
        "compressed_bytes": len(zipped),
        "source_snapshot_utc": snapshot_time(obj),
        "source_json_status": ("INVALID_ORIGINAL_JSON_PRESERVED_NOT_APPROVED_FOR_TRAINING"
            if source.suffix == ".json" and obj is None else
            "VALID_JSON" if source.suffix == ".json" else "SOURCE_CSV"),
    }
    if obj is not None:
        if source.name in BOARD_NAMES:
            entry["game_count"] = len(obj.get("nba_cba_games") or [])
        elif source.name == JC_NAME:
            entry["game_count"] = len(obj.get("games") or [])
        elif source.name == BOOK_NAME:
            entry["game_count"] = len(obj.get("games") or [])
        elif source.name == CONSENSUS_NAME:
            entry["game_count"] = len(obj.get("games") or [])
    entries.append(entry)
    return True


def source_files(path: Path, mode: str, workflow_name: str | None = None):
    if mode == "artifact":
        prefix = WORKFLOWS.get(workflow_name or "")
        if not prefix:
            raise ValueError("UNSUPPORTED_ORIGINAL_WORKFLOW_NAME")
        folders = [x for x in path.iterdir()
                   if x.is_dir() and not x.is_symlink() and x.name.startswith(prefix)]
        if len(folders) > 3:
            raise ValueError("UNEXPECTED_MULTIPLE_007_ACTION_ARTIFACTS")
        for folder in sorted(folders):
            for f in sorted(folder.rglob("*")):
                if f.is_file():
                    relative=f.relative_to(folder).as_posix()
                    # The artifact name is recorded in manifest metadata.
                    if safe_relative(relative):
                        yield f, relative
    elif mode == "backfill":
        for name in ("reports/daily", "reports/top10", "reports/hourly",
                     "reports/hourly-reviews", "reports/five-market-intraday",
                     "reports/two-market-intraday"):
            root=path/name
            if not root.is_dir():
                continue
            for f in sorted(root.rglob("*")):
                if f.is_file() and f.suffix in (".json", ".csv"):
                    relative=f.relative_to(path).as_posix()
                    if safe_relative(relative):
                        yield f, relative
    else:
        raise ValueError("UNRECOGNIZED_ARCHIVE_SOURCE_MODE")


def pick_day(sources, fallback=None):
    # A date from actual typed market evidence outranks workflow wall time.
    dates=[]
    for path, _ in sources:
        if path.name not in BOARD_NAMES | {JC_NAME, BOOK_NAME, CONSENSUS_NAME}:
            continue
        try:
            _, obj=read_source(path)
        except (ValueError, OSError, json.JSONDecodeError):
            continue
        if not isinstance(obj, dict):
            continue
        day=obj.get("requested_display_date") or obj.get("target_date")
        if isinstance(day, str) and DAY.fullmatch(day):
            dates.append(day)
    unique=set(dates)
    if len(unique)>1:
        raise ValueError("CONFLICTING_ORIGINAL_NBA_CAPTURE_DATE:"+",".join(sorted(unique)))
    if unique:
        return next(iter(unique))
    if fallback and DAY.fullmatch(fallback):
        return fallback
    raise ValueError("CAN_NOT_ESTABLISH_NBA_GAME_DAY_FROM_REAL_SOURCE")


def write_manifest(output: Path, *, workflow_name: str, run_id: str,
                   attempt: str, status: str, entries: list, origin: str,
                   source_conclusion: str):
    present={PurePosixPath(x["relative_original_source"]).name
             for x in entries
             if x["source_json_status"]!="INVALID_ORIGINAL_JSON_PRESERVED_NOT_APPROVED_FOR_TRAINING"}
    invalid=[x["relative_original_source"] for x in entries
             if x["source_json_status"]=="INVALID_ORIGINAL_JSON_PRESERVED_NOT_APPROVED_FOR_TRAINING"]
    # "raw company" can also be a direct reports/top10 observation file.
    has_book=BOOK_NAME in present or any(
        x["relative_original_source"].startswith("reports/top10/")
        for x in entries)
    missing=[
        label for label,ok in (
            ("FULL_NBA_BOARD", bool(present & BOARD_NAMES)),
            ("JC_THREE_MARKETS", JC_NAME in present),
            ("ALL_007_COMPANY_LINES_AND_WATER", has_book),
            ("MULTI_COMPANY_CONSENSUS", CONSENSUS_NAME in present),
        ) if not ok
    ]
    result={
        "schema_version":SCHEMA,
        "status":("PRESERVED_WITH_INVALID_SOURCE_JSON" if invalid else
                  status if not missing else "PARTIAL_OR_MISSING_SOURCES"),
        "original_actions_workflow":workflow_name,
        "original_run_id":str(run_id),
        "original_run_attempt":str(attempt),
        "original_run_conclusion":source_conclusion,
        "source_type":origin,
        "created_utc":datetime.now(timezone.utc).isoformat(),
        "archive_is_append_only_by_unique_run_attempt":True,
        "raw_json_bytes_preserved_inside_gzip":True,
        "source_stamps_are_capture_observation_times_not_book_update_times":True,
        "missing_required_source_categories":missing,
        "invalid_original_json_preserved_not_training_eligible":invalid,
        "file_count":len(entries),
        "total_original_bytes":sum(x["source_bytes"] for x in entries),
        "total_gzip_bytes":sum(x["compressed_bytes"] for x in entries),
        "files":sorted(entries,key=lambda x:x["relative_original_source"]),
        "no_original_production_model_modified":True,
        "no_official_model_or_shadow_predictions_recomputed":True,
    }
    target=output/"manifest.json"
    target.write_text(json.dumps(result,ensure_ascii=False,indent=2,sort_keys=True)+"\n")
    if json.loads(target.read_text()).get("file_count") != len(entries):
        raise RuntimeError("MANIFEST_WRITE_VERIFICATION_FAILED")
    return result


def archive_artifact(source: Path, archive_root: Path, workflow_name: str,
                     run_id: str, attempt: str, conclusion: str,
                     fallback_day: str | None = None):
    if workflow_name not in WORKFLOWS:
        raise ValueError("WORKFLOW_NOT_ALLOWED")
    if not IDENT.fullmatch(str(run_id)) or not IDENT.fullmatch(str(attempt)):
        raise ValueError("INVALID_GITHUB_RUN_ID_OR_ATTEMPT")
    source=source.resolve()
    if not source.is_dir():
        raise ValueError("ARTIFACT_INPUT_DIR_NOT_FOUND")
    sources=list(source_files(source,"artifact",workflow_name))
    if not sources:
        print("NO_007_CAPTURE_IN_THIS_COMPLETED_RUN",run_id,workflow_name)
        return None
    if len(sources)>MAX_FILES:
        raise ValueError("TOO_MANY_RAW_CAPTURE_FILES")
    day=pick_day(sources,fallback_day)
    output=archive_root / "reports/market-captures" / day / (
        "original-run-"+str(run_id)) / ("attempt-"+str(attempt))
    if output.exists():
        raise ValueError("ALREADY_ARCHIVED_THIS_EXACT_RUN_NEVER_REPLACE")
    output.mkdir(parents=True)
    entries=[]
    for src,logical in sources:
        add_file(source,src,logical,output,entries)
    if sum(x["source_bytes"] for x in entries)>MAX_TOTAL:
        raise ValueError("TOO_MANY_CAPTURE_BYTES")
    result=write_manifest(output,workflow_name=workflow_name,
        run_id=run_id,attempt=attempt,status="CAPTURE_ARCHIVED",
        entries=entries,origin="ORIGINAL_ACTION_WORKFLOW_ARTIFACT",
        source_conclusion=conclusion)
    print("DURABLE_007_CAPTURE",day,run_id,attempt,
          "files",result["file_count"],"raw_bytes",result["total_original_bytes"],
          "missing",result["missing_required_source_categories"])
    return output


def backfill_day(source: Path, archive_root: Path, day: str):
    if not DAY.fullmatch(day):
        raise ValueError("INVALID_BACKFILL_BEIJING_GAME_DATE")
    source=source.resolve()
    matched=[]
    for p,relative in source_files(source,"backfill"):
        # Source paths use their original own game-day directories.
        pieces=PurePosixPath(relative).parts
        if len(pieces)>=3 and pieces[2]==day:
            matched.append((p,relative))
    if not matched:
        raise ValueError("NO_EXISTING_RAW_NBA_ARCHIVE_FOR_DATE_"+day)
    if len(matched)>MAX_FILES:
        raise ValueError("TOO_MANY_BACKFILL_FILES")
    output=archive_root/"reports/market-captures"/day/"main-existing-historical-backfill"
    if output.exists():
        raise ValueError("NEVER_OVERWRITE_EXISTING_HISTORICAL_BACKFILL")
    output.mkdir(parents=True)
    entries=[]
    for p,logical in matched:
        add_file(source,p,logical,output,entries)
    if sum(x["source_bytes"] for x in entries)>MAX_TOTAL:
        raise ValueError("BACKFILL_INPUT_TOO_LARGE")
    result=write_manifest(output,workflow_name="MAIN_HISTORICAL_PRETIP_FILES",
        run_id="0",attempt="0",status="HISTORICAL_REMAINING_FILES_BACKFILLED",
        entries=entries,origin="ORIGINAL_MAIN_ARCHIVED_SOURCE_FILES",
        source_conclusion="UNKNOWN_HISTORICAL")
    print("DURABLE_BACKFILL_007",day,"files",result["file_count"],
          "raw_bytes",result["total_original_bytes"],
          "missing",result["missing_required_source_categories"])
    return output


def backfill_all(source: Path, archive_root: Path):
    days=set()
    for base in ("reports/daily","reports/top10","reports/hourly",
                 "reports/hourly-reviews","reports/five-market-intraday",
                 "reports/two-market-intraday"):
        root=source/base
        if root.is_dir():
            days.update(child.name for child in root.iterdir()
                        if child.is_dir() and not child.is_symlink()
                        and DAY.fullmatch(child.name))
    done=[]
    for day in sorted(days):
        output=archive_root/"reports/market-captures"/day/"main-existing-historical-backfill"
        if output.exists():
            print("HISTORICAL_007_ALREADY_ARCHIVED_NEVER_OVERWRITE",day)
            continue
        try:
            result=backfill_day(source,archive_root,day)
            done.append((day,str(result)))
        except ValueError as e:
            if str(e)=="NO_EXISTING_RAW_NBA_ARCHIVE_FOR_DATE_"+day:
                print("HISTORICAL_007_DATE_NO_ELIGIBLE_RAW_CAPTURE",day)
                continue
            raise
    print("HISTORICAL_007_DAILY_DATES_ARCHIVED",len(done),[d for d,_ in done])
    return done


def selftest():
    from tempfile import TemporaryDirectory
    with TemporaryDirectory() as temp:
        root=Path(temp)
        artifact=root/"a"/"titan007-three-analysis-2026-11-03"
        artifact.mkdir(parents=True)
        (artifact/"titan007_three_joined.json").write_text(json.dumps({
            "requested_display_date":"2026-11-03",
            "captured_at_utc":"2026-11-02T10:02:00+00:00",
            "nba_cba_games":[{"game_id":"728298","home_team":"骑士",
                              "away_team":"雷霆"}]},ensure_ascii=False))
        (artifact/"nba_jingcai_three_market.json").write_text(json.dumps({
            "target_date":"2026-11-03","games":[{"game_id":"728298",
            "markets":{"handicap":{"current":{"line":-6.5,"first_side":1.65,
                                                   "second_side":1.75}}}}]}))
        (artifact/"nba_top10_companies.json").write_text(json.dumps({
            "target_date":"2026-11-03","games":[{"game_id":"728298",
            "markets":{"full_spread":{"companies":[{"company_id":"3",
                 "current":{"line":4.5,"first_side_water":.98,
                             "second_side_water":.88}}]}}}]}))
        (artifact/"nba_market_consensus.json").write_text(json.dumps({
            "target_date":"2026-11-03","games":[{"game_id":"728298",
                                                   "markets":{}}]}))
        out=archive_artifact(root/"a",root/"b",list(WORKFLOWS)[0],
                             "123456","1","failure")
        assert out is not None
        manifest=json.loads((out/"manifest.json").read_text())
        assert manifest["status"]=="CAPTURE_ARCHIVED"
        assert manifest["file_count"]==4
        assert not manifest["missing_required_source_categories"]
        assert manifest["original_run_conclusion"]=="failure"
        for e in manifest["files"]:
            raw=gzip.decompress((out/e["compressed_file"]).read_bytes())
            assert sha(raw)==e["source_sha256"]
            assert sha((out/e["compressed_file"]).read_bytes())==e["gzip_sha256"]
            assert raw==(artifact/e["relative_original_source"]).read_bytes()
        try:
            archive_artifact(root/"a",root/"b",list(WORKFLOWS)[0],
                             "123456","1","success")
        except ValueError as err:
            assert "NEVER_REPLACE" in str(err)
        else:
            raise AssertionError("SAME_RUN_WAS_ALLOWED_TO_OVERWRITE")
        # A historical producer may have inadvertently written multiple
        # JSON documents consecutively. Preserve bytes and mark source BAD;
        # never silently treat the concatenation as a valid model sample.
        (artifact/"nba_malformed.json").write_bytes(b'{"game_id":"A"}\n{"game_id":"B"}\n')
        anomaly=archive_artifact(root/"a",root/"b",list(WORKFLOWS)[0],
                                 "123458","1","failure")
        assert anomaly is not None
        bad=json.loads((anomaly/"manifest.json").read_text())
        assert bad["status"]=="PRESERVED_WITH_INVALID_SOURCE_JSON"
        assert any("nba_malformed.json" in x for x in
                   bad["invalid_original_json_preserved_not_training_eligible"])
        assert (anomaly/"files/nba_malformed.json.gz").is_file()
        assert gzip.decompress(
            (anomaly/"files/nba_malformed.json.gz").read_bytes()
        )==(artifact/"nba_malformed.json").read_bytes()
        assert not safe_relative("../token.json")
        assert not safe_relative("pushplus_status.json")
        (artifact/"nba_extra.json").write_text('{"api_key":"DO_NOT_ARCHIVE"}')
        try:
            archive_artifact(root/"a",root/"b",list(WORKFLOWS)[0],
                             "123457","1","success")
        except ValueError as err:
            assert "SECRET_FIELD" in str(err)
        else:
            raise AssertionError("SECRET_WAS_ALLOWED_IN_ARCHIVED_SOURCE")
    print("NBA_DURABLE_ALL_007_MARKET_COMPANY_JINGCAI_CAPTURE_SELFTEST_PASS")


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--selftest",action="store_true")
    parser.add_argument("--artifact-root")
    parser.add_argument("--main-repo")
    parser.add_argument("--archive-root")
    parser.add_argument("--workflow-name")
    parser.add_argument("--run-id")
    parser.add_argument("--attempt")
    parser.add_argument("--conclusion",default="unknown")
    parser.add_argument("--fallback-date")
    parser.add_argument("--backfill-date")
    parser.add_argument("--backfill-all",action="store_true")
    a=parser.parse_args()
    if a.selftest:
        selftest()
        return
    if not a.archive_root:
        raise SystemExit("REQUIRES_ARCHIVE_BRANCH_WORKTREE")
    target=Path(a.archive_root)
    if a.backfill_all:
        if not a.main_repo:
            raise SystemExit("REQUIRES_SEPARATE_MAIN_WORKTREE")
        backfill_all(Path(a.main_repo),target)
    elif a.backfill_date:
        if not a.main_repo:
            raise SystemExit("REQUIRES_SEPARATE_MAIN_WORKTREE")
        backfill_day(Path(a.main_repo),target,a.backfill_date)
    else:
        if not a.artifact_root or not a.workflow_name or not a.run_id or not a.attempt:
            raise SystemExit("REQUIRES_ORIGINAL_ACTION_IDENTITY_AND_BYTES")
        archive_artifact(Path(a.artifact_root),target,a.workflow_name,
                         a.run_id,a.attempt,a.conclusion,a.fallback_date)


if __name__=="__main__":
    main()
