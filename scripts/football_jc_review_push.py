#!/usr/bin/env python3
"""Send the already settled previous-sale-day football review."""
import argparse
from datetime import date, datetime, timedelta
import hashlib
from html import escape
import json
import os
from pathlib import Path
import sys
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "analysis"))
from sport_match_final_review_html import render, result_score
from football_jc_final_2130 import BJ
from sports_postgame_slot import validate
from football_jc_slot_push import payload_size
from pushplus_mobile import MAX_BYTES, save_status, send


def prepare(archive, day, repo, token):
    with ZipFile(archive) as bundle:
        report = json.loads(bundle.read("review.json"))
    if (report.get("sport") != "football" or report.get("beijing_day") != day.isoformat()
            or report.get("prediction_source") != "LATEST_VERIFIED_PREKICKOFF_PER_MATCH_IMMUTABLE"
            or not report.get("matches")):
        raise ValueError("EXPECTED_PREVIOUS_DAY_PER_MATCH_FOOTBALL_REVIEW")
    if not any(result_score("football", row)[1] is not None for row in report["matches"]):
        raise ValueError("FOOTBALL_REVIEW_HAS_NO_VERIFIED_RESULTS")
    tag = f"football-jc-review-latest-{day:%Y%m%d}"
    release = f"https://github.com/{repo}/releases"
    if archive.name.startswith(f"{tag}-send-"):
        url = f"{release}/download/{tag}/{archive.name}"
    else:
        url = f"{release}/tag/{tag}"
    url = escape(url, quote=True)
    link = f'<p><a href="{url}">完整复盘归档</a></p>'
    pending = sum(result_score("football", row)[1] is None for row in report["matches"])
    status = f"（{pending}场赛果未核实）" if pending else ""
    payload = {"title": f"北京时间{day.month}月{day.day}日 竞彩足球复盘{status}",
               "html": render(report) + link}
    if payload_size(payload, token) > MAX_BYTES:
        payload["html"] = render(report, timing_only=True) + link
    if payload_size(payload, token) > MAX_BYTES:
        raise ValueError("FOOTBALL_REVIEW_PUSH_PAYLOAD_TOO_LARGE")
    return payload


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--day", required=True, type=date.fromisoformat)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--preview", required=True, type=Path)
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args()
    token = os.environ.get("FOOTBALL_PUSHPLUS_TOKEN", "")
    payload = prepare(args.archive, args.day, args.repo, token)
    args.preview.write_text(payload["html"], encoding="utf-8")
    if args.receipt:
        now = datetime.now(BJ)
        validate("football-review", os.environ["GITHUB_EVENT_NAME"],
                 os.getenv("CLOUDFLARE_SLOT_UTC", ""), now,
                 os.environ["GITHUB_REF"], os.getenv("POSTGAME_CRON", ""))
        if args.day != now.date() - timedelta(days=1):
            raise ValueError("FOOTBALL_REVIEW_IS_NOT_FOR_YESTERDAY")
        response = send(payload, token)
        save_status(args.receipt, {
            **response,
            "review_day_beijing": args.day.isoformat(),
            "scheduled_slot_beijing": "13:00",
            "run_id": os.environ["GITHUB_RUN_ID"],
            "payload_sha256": hashlib.sha256(payload["html"].encode()).hexdigest(),
        })
        print("FOOTBALL_REVIEW_API_ACCEPTED", args.day)


if __name__ == "__main__":
    main()
