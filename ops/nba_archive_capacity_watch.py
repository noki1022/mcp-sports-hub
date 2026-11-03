#!/usr/bin/env python3
"""Read-only GitHub capacity/long-lived raw evidence monitor, isolated from production.

GitHub repository API size is an approximate KiB indicator, not exact .git usage.
Never delete, rewrite, deduplicate or expire raw captured evidence here.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

ARCHIVE = "archive/nba-market-captures"
WARN_KIB = 400 * 1024
CRITICAL_KIB = 800 * 1024


def api(path, token):
    req = Request("https://api.github.com" + path, headers={
        "Authorization": "Bearer " + token,
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "nba-archive-capacity-watch",
    })
    with urlopen(req, timeout=25) as response:
        return json.load(response)


def capture_date(path):
    prefix = "reports/market-captures/"
    if not path.startswith(prefix):
        return None
    day = path[len(prefix):].split("/", 1)[0]
    try:
        datetime.strptime(day, "%Y-%m-%d")
        return day
    except ValueError:
        return None


def assess(meta, main, archive, branch, now):
    if main.get("truncated") or archive.get("truncated"):
        raise ValueError("GITHUB_TREE_TRUNCATED_CAPACITY_AUDIT_NOT_TRUSTWORTHY")
    size_kib = meta.get("size")
    if not isinstance(size_kib, int) or size_kib < 0:
        raise ValueError("INVALID_REPOSITORY_SIZE")
    main_files = main.get("tree", [])
    archives = archive.get("tree", [])
    if not isinstance(main_files, list) or not isinstance(archives, list):
        raise ValueError("INVALID_GITHUB_TREE")
    raw = [f for f in archives if f.get("type") == "blob"
           and capture_date(f.get("path", ""))]
    gz = [f for f in raw if f["path"].endswith(".gz")]
    manifest = [f for f in raw if f["path"].endswith("/manifest.json")]
    daily = [f for f in main_files if f.get("type") == "blob"
             and f.get("path", "").startswith("reports/daily/")]
    days = Counter(capture_date(f["path"]) for f in gz)
    last_str = branch["commit"]["commit"]["committer"]["date"]
    last = datetime.fromisoformat(last_str.replace("Z", "+00:00"))
    age = round(max(0, (now - last).total_seconds() / 3600), 1)
    critical = []
    warnings = []
    if size_kib >= CRITICAL_KIB:
        critical.append("GIT_REPO_NEARING_RECOMMENDED_1GB_SCALE")
    elif size_kib >= WARN_KIB:
        warnings.append("GIT_REPO_CAPACITY_TREND_NEEDS_PLAN")
    if not gz or not manifest:
        critical.append("LONG_LIVED_SOURCE_ARCHIVE_NOT_PRESENT")
    if age > 48:
        warnings.append("ARCHIVE_BRANCH_STALE_OVER_48H_CHECK_CAPTURE_WORKFLOWS")
    if any(f.get("size", 0) >= 1_000_000 for f in main_files if f.get("type") == "blob"):
        warnings.append("LARGE_BLOB_ON_MAIN_REVIEW_GIT_GROWTH")
    return {
        "checked_at_utc": now.isoformat(),
        "repository": meta["full_name"],
        "repository_size_approx_kib": size_kib,
        "repository_size_approx_mib": round(size_kib / 1024, 2),
        "main_daily_report_tracked_files": len(daily),
        "main_daily_report_current_tree_bytes": sum(f.get("size", 0) for f in daily),
        "archive_branch": ARCHIVE,
        "archive_raw_gzip_files": len(gz),
        "archive_manifest_files": len(manifest),
        "archive_gzip_current_tree_bytes": sum(f.get("size", 0) for f in gz),
        "archive_raw_gzip_by_game_date": dict(sorted(days.items())),
        "archive_branch_last_commit_utc": last.isoformat(),
        "archive_branch_last_commit_age_hours": age,
        "warning_at_mib": WARN_KIB // 1024,
        "critical_at_mib": CRITICAL_KIB // 1024,
        "critical": critical,
        "warnings": warnings,
        "limitations": [
            "API size is approximate, not on-disk .git or Git LFS usage.",
            "Tree sums exclude Git history and cannot prove complete capture coverage.",
            "GitHub Actions artifacts are temporary, not long-lived storage.",
            "This job never mutates source data or production workflows.",
        ],
    }


def selftest():
    now = datetime(2026, 11, 3, tzinfo=timezone.utc)
    meta = {"full_name": "test/repo", "size": 7559}
    main = {"tree": [{"type": "blob", "path": "reports/daily/x.json", "size": 22}]}
    archive = {"tree": [
        {"type": "blob", "path": "reports/market-captures/2026-11-03/a/manifest.json", "size": 9},
        {"type": "blob", "path": "reports/market-captures/2026-11-03/a/files/a.json.gz", "size": 11},
    ]}
    branch = {"commit": {"commit": {"committer": {"date": "2026-11-03T00:00:00Z"}}}}
    r = assess(meta, main, archive, branch, now)
    assert r["archive_raw_gzip_files"] == 1 and r["archive_manifest_files"] == 1
    assert not r["critical"] and not r["warnings"]
    meta["size"] = CRITICAL_KIB
    assert assess(meta, main, archive, branch, now)["critical"]
    archive["tree"] = []
    assert "LONG_LIVED_SOURCE_ARCHIVE_NOT_PRESENT" in assess(meta, main, archive, branch, now)["critical"]
    archive["truncated"] = True
    try:
        assess(meta, main, archive, branch, now)
    except ValueError:
        pass
    else:
        raise AssertionError("truncated archive tree must not be accepted")
    print("ARCHIVE_CAPACITY_MONITOR_TESTS_PASSED")


def write_summary(report):
    sev = "CRITICAL" if report["critical"] else "WARNING" if report["warnings"] else "OK"
    lines = [
        "# NBA long-lived raw data capacity",
        "",
        f"**Health:** {sev}",
        f"**Repository API estimate:** {report['repository_size_approx_mib']} MiB",
        f"**Archive compressed evidence:** {report['archive_raw_gzip_files']} files",
        f"**Archive manifests:** {report['archive_manifest_files']}",
        f"**Archive last commit age:** {report['archive_branch_last_commit_age_hours']} hours",
        "",
        "Git history is not included in tree-byte counts. This workflow never deletes original data.",
        *["- ERROR: " + s for s in report["critical"]],
        *["- WARN: " + s for s in report["warnings"]],
    ]
    output = "\n".join(lines) + "\n"
    print(output)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as handle:
            handle.write(output)


def notify_critical(report):
    token = os.getenv("PUSHPLUS_TOKEN", "")
    if not token or not report["critical"]:
        return
    body = {
        "token": token,
        "title": "NBA原始数据归档严重预警",
        "content": "GitHub归档需要检查：" + "，".join(report["critical"])
                   + "\n仓库约 " + str(report["repository_size_approx_mib"]) + " MiB。"
                   + "\nhttps://github.com/" + report["repository"] + "/actions",
        "template": "txt",
    }
    payload = json.dumps(body).encode("utf-8")
    req = Request("https://www.pushplus.plus/send", data=payload,
                  headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urlopen(req, timeout=12) as response:
            accepted = json.load(response)
        if str(accepted.get("code")) != "200":
            print("::warning::ARCHIVE_CRITICAL_PUSHPLUS_API_NOT_ACCEPTED")
    except (HTTPError, URLError, ValueError):
        print("::warning::ARCHIVE_CRITICAL_PUSHPLUS_UNAVAILABLE")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--selftest", action="store_true")
    p.add_argument("--notify-critical", action="store_true")
    p.add_argument("--out", default="nba-archive-capacity-health.json")
    args = p.parse_args()
    if args.selftest:
        selftest()
        return 0
    token = os.environ.get("GITHUB_TOKEN", "")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if not token or len(repo.split("/")) != 2:
        raise ValueError("GITHUB_TOKEN_AND_REPOSITORY_REQUIRED")
    root = "/repos/" + quote(repo, safe="/")
    report = assess(
        api(root, token),
        api(root + "/git/trees/main?recursive=1", token),
        api(root + "/git/trees/" + quote(ARCHIVE, safe="") + "?recursive=1", token),
        api(root + "/branches/" + quote(ARCHIVE, safe="/"), token),
        datetime.now(timezone.utc),
    )
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    write_summary(report)
    for item in report["warnings"]:
        print("::warning::" + item)
    for item in report["critical"]:
        print("::error::" + item)
    if args.notify_critical:
        notify_critical(report)
    return 1 if report["critical"] else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (HTTPError, URLError, KeyError, ValueError) as exc:
        print("::error::NBA_ARCHIVE_CAPACITY_MONITOR_FAILED:" + str(exc))
        sys.exit(2)
