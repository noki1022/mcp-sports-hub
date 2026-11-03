#!/usr/bin/env python3
"""iPhone GitHub Actions entrypoint: read-only search and optional exact restore."""
import html
import json
import os
from pathlib import Path
import subprocess
import sys

def main():
    root = Path(os.environ["RUNNER_TEMP"])
    archive = root / "archive"
    cmd = [sys.executable, "ops/nba_raw_vault.py", "--archive-root", str(archive),
           "search", "--verify", "--limit", "50", "--output", str(root / "vault-search.jsonl")]
    for env, flag in (("VAULT_DAY", "--day"), ("VAULT_GAME_ID", "--game-id"),
                      ("VAULT_SOURCE", "--source")):
        if os.environ.get(env, "").strip():
            cmd.extend([flag, os.environ[env].strip()])
    subprocess.run(cmd, check=True)
    manifest = os.environ.get("VAULT_MANIFEST", "").strip()
    source = os.environ.get("VAULT_RESTORE_SOURCE", "").strip()
    if manifest or source:
        if not manifest or not source:
            raise ValueError("RESTORE_REQUIRES_EXACT_MANIFEST_AND_SOURCE")
        suffix = Path(source).suffix
        if suffix not in (".json", ".csv"):
            raise ValueError("INVALID_RESTORE_SUFFIX")
        subprocess.run([sys.executable, "ops/nba_raw_vault.py", "--archive-root", str(archive),
                        "restore", "--manifest", manifest, "--source", source,
                        "--output", str(root / ("recovered-original" + suffix))], check=True)
    p = root / "vault-search.jsonl"
    entries = [json.loads(line) for line in p.read_text().splitlines()] if p.is_file() else []
    with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a") as summary:
        summary.write("# NBA 原始数据检索\n\n")
        summary.write("**本次最多显示 50 条，已校验记录：** " + str(len(entries)) + "\n\n")
        summary.write("| 北京时间比赛日期 | 原始数据来源 | 抓取时间 UTC |\n|---|---|---|\n")
        for row in entries:
            safe = lambda x: html.escape(str(x or "")).replace("|", "/")
            summary.write("| " + safe(row["game_date_beijing"]) + " | " +
                          safe(row["source"]) + " | " +
                          safe(row["source_snapshot_utc"]) + " |\n")
        summary.write("\n长期源数据在 archive/nba-market-captures，Artifacts 下载文件仅临时保存 7 天。\n")
        if list(root.glob("recovered-original.*")):
            summary.write("\n**恢复成功：原始文件已逐字节 SHA-256 校验，见本次运行的 Artifacts。**\n")
    print("NBA_RAW_MOBILE_SEARCH", len(entries), "records", "restored", bool(manifest))

if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        print("NBA_RAW_MOBILE_QUERY_FAILED", repr(exc), file=sys.stderr)
        sys.exit(2)
