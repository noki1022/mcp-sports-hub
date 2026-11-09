#!/usr/bin/env python3
"""Send an already settled 21:00 football review without re-scoring it."""
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
from football_jc_single_final_review import render
from football_jc_final_2130 import BJ
from football_jc_capture_slot import validate_send_window
from football_jc_slot_push import payload_size
from pushplus_mobile import MAX_BYTES, save_status, send


def prepare(archive, day, repo, token):
    with ZipFile(archive) as bundle:
        report = json.loads(bundle.read("review.json"))
    if (report.get("schema_version") != "football-jc-2100-single-official-review-v1"
            or report.get("final_date_beijing") != day.isoformat()
            or report.get("scoring_source") != "ONLY_2100_FUSED_FROZEN_FORECAST"
            or not report.get("games")):
        raise ValueError("EXPECTED_PREVIOUS_DAY_OFFICIAL_FOOTBALL_2100_REVIEW")
    tag = f"football-jc-review-2100-{day:%Y%m%d}"
    url = escape(f"https://github.com/{repo}/releases/tag/{tag}", quote=True)
    link = f'<p><a href="{url}">完整复盘归档</a></p>'
    payload = {"title": f"北京时间{day.month}月{day.day}日 竞彩足球复盘",
               "html": render(report) + link}
    if payload_size(payload, token) > MAX_BYTES:
        payload["html"] = render({**report, "games": []}) + link
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
        validate_send_window("1300", now)
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
