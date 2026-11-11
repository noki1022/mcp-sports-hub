#!/usr/bin/env python3
"""Restore only JSON snapshots from the existing immutable football raw vault.

No extraction of paths or execution of archive content; missing history is a
normal first-capture condition. Does not modify/delete/upload any remote asset.
"""
import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
from datetime import datetime,timedelta,timezone
from zipfile import ZipFile, BadZipFile

import football_007_analysis_extract as analysis

MAX_ARCHIVE=60_000_000
MAX_JSON=20_000_000
FORM_MAX_AGE = timedelta(hours=3)
FORM_FIELDS = ("home_last5", "away_last5", "h2h")
MATCH_FIELDS = ("match_id", "jc_number", "home_team_id_007", "away_team_id_007", "kickoff_beijing")


def snapshot_bytes(raw):
    if len(raw)>MAX_ARCHIVE:raise ValueError('ARCHIVE_TOO_LARGE')
    with ZipFile(io.BytesIO(raw)) as z:
        matches=[i for i in z.infolist() if i.filename=='football-output/football_007_snapshot.json']
        if len(matches)!=1 or matches[0].file_size>MAX_JSON:raise ValueError('SNAPSHOT_MEMBER_INVALID')
        data=z.read(matches[0])
    doc=json.loads(data)
    if not isinstance(doc,dict) or doc.get('schema_version')!='football-jc-007-v1':raise ValueError('INVALID_SNAPSHOT')
    return data


def gh(*args):
    return subprocess.run(['gh',*args],check=True,capture_output=True,timeout=20).stdout


def verified_form(raw, snapshot):
    """Reparse archived pages whose original bytes match their source proof."""
    records = []
    with ZipFile(io.BytesIO(raw)) as archive:
        for game in snapshot["games"]:
            if game.get("analysis_source_status") != "007_EMBEDDED_JSON_VALIDATED":
                continue
            try:
                proof = game["analysis_source_evidence"]
                observed = analysis.parse_dt(proof["captured_at_utc"])
                kickoff = analysis.parse_dt(game["kickoff_beijing"])
                captured = analysis.parse_dt(snapshot["captured_at_utc"])
                if not observed <= captured < kickoff:
                    continue
                member = archive.getinfo(f'football-output/raw/analysis_{game["match_id"]}.html.gz')
                if member.file_size > analysis.MAX_HTML:
                    continue
                with gzip.GzipFile(fileobj=io.BytesIO(archive.read(member))) as source:
                    page = source.read(analysis.MAX_HTML + 1)
                if len(page) > analysis.MAX_HTML or hashlib.sha256(page).hexdigest() != proof["sha256"]:
                    continue
                parsed = analysis.extract(page, game, proof["captured_at_utc"])
                if min(len(parsed["home_last5"]), len(parsed["away_last5"])) < 3:
                    continue
                records.append({
                    **{key: game[key] for key in MATCH_FIELDS},
                    **{key: parsed[key] for key in FORM_FIELDS},
                    "observed_at_utc": observed.isoformat(),
                    "analysis_sha256": proof["sha256"],
                    "sale_day": snapshot["jc_sale_day_beijing"],
                })
            except (OSError, EOFError, KeyError, TypeError, ValueError, BadZipFile):
                continue
    return records


def reuse_form(snapshot, records):
    captured = analysis.parse_dt(snapshot["captured_at_utc"])
    used = 0
    for game in snapshot["games"]:
        if (not game.get("analysis_source_status", "").startswith("UNAVAILABLE_")
                or game.get("analysis_source_evidence")
                or min(len(game["home_last5"]), len(game["away_last5"])) >= 3):
            continue
        kickoff = analysis.parse_dt(game["kickoff_beijing"])
        eligible = []
        for record in records:
            if record["sale_day"] != snapshot["jc_sale_day_beijing"]:
                continue
            if any(game.get(key) is None or game[key] != record[key] for key in MATCH_FIELDS):
                continue
            observed = analysis.parse_dt(record["observed_at_utc"])
            if timedelta(0) < captured - observed <= FORM_MAX_AGE and captured < kickoff:
                eligible.append(record)
        if not eligible:
            continue
        prior = max(eligible, key=lambda record: record["observed_at_utc"])
        game.update({key: prior[key] for key in FORM_FIELDS})
        game["form_observed_at"] = game["h2h_observed_at"] = prior["observed_at_utc"]
        game["archived_form_007"] = {key: prior[key] for key in
                                    ("observed_at_utc", "analysis_sha256", "archive_asset")}
        game["data_gaps"] = [gap for gap in game["data_gaps"]
                             if gap not in ("RECENT_FIVE_NOT_YET_PARSED", "H2H_NOT_YET_PARSED")]
        if not game["h2h"]:
            game["data_gaps"].append("H2H_EMPTY_OR_NOT_LISTED")
        used += 1
    return used


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--reuse-form", type=Path, metavar="SNAPSHOT")
    args = parser.parse_args()
    root=Path('football-history');root.mkdir(exist_ok=True)
    if args.reuse_form:
        snapshot = json.loads(args.reuse_form.read_text(encoding="utf-8"))
        records = []
        for path in sorted(root.glob("verified_form_*.json")):
            records.extend(json.loads(path.read_text(encoding="utf-8")))
        count = reuse_form(snapshot, records)
        if count:
            temporary = args.reuse_form.with_suffix(".tmp")
            temporary.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            temporary.replace(args.reuse_form)
        print("FOOTBALL_ARCHIVED_FORM_REUSED", count)
        return
    repo=os.environ['GH_REPO'];today=datetime.now(timezone(timedelta(hours=8))).date()
    stats={'restored':0,'skipped':0,'missing_release_days':0}
    seen=set();total=0
    for offset in range(3):
        tag='football-007-raw-'+(today-timedelta(days=offset)).strftime('%Y%m%d')
        try:
            info=json.loads(gh('api',f'repos/{repo}/releases/tags/{tag}'))
        except (subprocess.SubprocessError,ValueError):stats['missing_release_days']+=1;continue
        for asset in sorted(info.get('assets', []), key=lambda item: item.get("created_at", ""), reverse=True):
            if not asset['name'].startswith(tag+'-run-') or not asset['name'].endswith('.zip'):continue
            size=asset.get('size',MAX_ARCHIVE+1)
            if not 0<size<=MAX_ARCHIVE or total+size>500_000_000:
                stats['skipped']+=1;continue
            total+=size
            try:
                raw=gh('api','-H','Accept: application/octet-stream',f'repos/{repo}/releases/assets/{asset["id"]}')
                data=snapshot_bytes(raw);digest=hashlib.sha256(data).hexdigest()
                if digest in seen:continue
                seen.add(digest)
                (root/f'football_007_snapshot_{digest}.json').write_bytes(data)
                stats['restored']+=1
                captured = json.loads(data)
                recent = datetime.now(timezone.utc) - analysis.parse_dt(captured["captured_at_utc"])
                records = verified_form(raw, captured) if timedelta(0) <= recent <= FORM_MAX_AGE else []
                if records:
                    for record in records:
                        record["archive_asset"] = asset["name"]
                    target = root / f"verified_form_{digest}.json"
                    pending = target.with_suffix(".tmp")
                    pending.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")
                    pending.replace(target)
            except (subprocess.SubprocessError,ValueError,OSError,KeyError,BadZipFile,RuntimeError):stats['skipped']+=1
    print('FOOTBALL_HISTORY_RESTORE',json.dumps(stats))

if __name__=='__main__':main()
