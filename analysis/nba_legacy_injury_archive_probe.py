#!/usr/bin/env python3
"""P0 historical NBA official injury archive availability probe (2022–2024).

Uses MIT-licensed nbainjuries API to parse actual NBA injury PDFs.
Bounded, robots-respecting sample; nominal filename hour does NOT prove
original issue time. Never stores full original PDF/medical rows in Git.
This is a source admission test, NOT an impact coefficient validation.
"""
from __future__ import annotations
import argparse,hashlib,json,re,time,urllib.error,urllib.request,urllib.robotparser
from collections import Counter
from datetime import datetime,timedelta,timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT="https://ak-static.cms.nba.com"
UA="NBAInjuryHistoricalResearch/1.0 (bounded official-source reproducibility probe)"
ET=ZoneInfo("America/New_York")
# Four sampled NBA regular-season windows from 2022-23 and 2023-24.
# Time slots follow package's own historical naming convention.
DATES=("2022-11-15","2023-01-12","2023-11-15","2024-01-12")
SLOTS=("03PM","05PM")
MAX_PDF_BYTES=1_500_000

def url_for(day,slot):
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}",day) or not re.fullmatch(r"(0[1-9]|1[0-2])(AM|PM)",slot):
        raise ValueError("UNSAFE_TIME")
    return f"{ROOT}/referee/injury/Injury-Report_{day}_{slot}.pdf"

def parse_nominal(day,slot):
    hour=int(slot[:2])%12+(12 if slot[-2:]=="PM" else 0)
    return datetime.fromisoformat(day).replace(hour=hour,minute=0,tzinfo=ET).astimezone(timezone.utc)

def probe_policy():
    robots=ROOT+"/robots.txt"
    parser=urllib.robotparser.RobotFileParser()
    try:
        with urllib.request.urlopen(urllib.request.Request(robots,headers={"User-Agent":UA}),timeout=12) as r:
            data=r.read(100001)
            if len(data)>100000:raise RuntimeError("UNBOUNDED_ROBOTS")
            parser.parse(data.decode("utf-8","replace").splitlines())
    except urllib.error.HTTPError as e:
        if e.code not in (404,410):
            return False,"ROBOTS_HTTP_"+str(e.code)
        parser.parse([])
    except Exception as exc:
        return False,"ROBOTS_UNREACHABLE_"+type(exc).__name__
    for day in DATES:
        for slot in SLOTS:
            if not parser.can_fetch(UA,url_for(day,slot)):
                return False,"ROBOTS_DISALLOW"
    return True,"PERMITTED_TO_PROBE"

def run(out):
    policy,reason=probe_policy()
    audit={"source":"Official NBA archived PDF via nbainjuries 1.1.1",
        "sample_dates":DATES,"sample_slots":SLOTS,"robust_source_permission":reason,
        "timestamp_proof":"NOMINAL_PDF_FILENAME_ONLY_NOT_VERIFIED_FIRST_PUBLICATION",
        "official_game_tipoff_compared":False,
        "verified_pretip_training_records":0,
        "individual_player_impact_validated":False,
        "production_admission":False,
        "probes":[]}
    if not policy:
        audit["status"]="BLOCKED_SOURCE_PERMISSION"
        Path(out).write_text(json.dumps(audit,indent=2)+"\n")
        print("LEGACY_INJURY_PROBE",audit["status"],reason)
        return audit
    import nbainjuries.injury as injury
    successes=0
    for day in DATES:
        for slot in SLOTS:
            report={"date_et":day,"time_et":slot,"nominal_utc":parse_nominal(day,slot).isoformat(),
                    "source_url":url_for(day,slot),"status":"UNTESTED"}
            try:
                # This is the official, bounded archival URL format from nbainjuries.
                # The package normally downloads twice (once validate, once tabula);
                # read only if content appears bounded and PDF.
                url=report["source_url"]
                req=urllib.request.Request(url,headers={"User-Agent":UA})
                with urllib.request.urlopen(req,timeout=20) as r:
                    data=r.read(MAX_PDF_BYTES+1)
                    if r.status!=200:raise RuntimeError("NON_200_PDF")
                if len(data)>MAX_PDF_BYTES:raise ValueError("UNBOUNDED_REPORT_PDF")
                if not data.startswith(b"%PDF"):raise ValueError("HTML_NOT_PDF")
                report["bytes"]=len(data)
                report["sha256"]=hashlib.sha256(data).hexdigest()
                # Use package parser on the single already-downloaded local PDF,
                # rather than make additional remote calls or infer locations.
                from tempfile import TemporaryDirectory
                with TemporaryDirectory() as tmp:
                    path=Path(tmp)/Path(url).name;path.write_bytes(data)
                    ts=datetime.fromisoformat(day).replace(hour=int(slot[:2])%12+(12 if slot[-2:]=="PM" else 0))
                    parsed=injury.get_reportdata(ts,local=True,localdir=tmp,return_df=True)
                required={"Game Date","Game Time","Matchup","Team","Player Name","Current Status","Reason"}
                if not required.issubset(parsed.columns):raise ValueError("BAD_PARSED_COLUMNS")
                report["player_rows"]=int(parsed["Player Name"].notna().sum())
                report["unique_matchups"]=int(parsed["Matchup"].nunique())
                report["teams"]=int(parsed["Team"].nunique())
                report["parsed_game_dates"]=sorted(str(x) for x in parsed["Game Date"].dropna().unique())[:7]
                if report["player_rows"]<1 or report["unique_matchups"]<1:raise ValueError("EMPTY_PARSED_REPORT")
                report["status"]="ARCHIVE_PDF_PARSED_PUBLISH_TIME_NOT_PROVEN"
                successes+=1
            except urllib.error.HTTPError as exc:
                report["status"]="HTTP_"+str(exc.code)
            except (urllib.error.URLError,TimeoutError) as exc:
                report["status"]="SOURCE_NETWORK_"+type(exc).__name__
            except Exception as exc:
                report["status"]="PARSE_OR_QUALITY_FAIL_"+type(exc).__name__
                report["detail"]=str(exc)[:140]
            audit["probes"].append(report)
            print("INJURY_LEGACY_SAMPLE",json.dumps({k:v for k,v in report.items() if k in ("date_et","time_et","status","player_rows","unique_matchups")}))
            time.sleep(.2)
    audit["real_pdf_parsed_samples"]=successes
    audit["sample_attempts"]=len(audit["probes"])
    audit["status"]="ARCHIVE_SAMPLES_VERIFIED_BUT_RELEASE_TIMES_UNPROVEN" if successes>=2 else "BLOCKED_INSUFFICIENT_ARCHIVE_ACCESS"
    Path(out).write_text(json.dumps(audit,indent=2,ensure_ascii=False)+"\n")
    print("NBA_LEGACY_INJURY_ADMISSION",audit["status"],successes)
    return audit

def self_test():
    assert url_for("2023-01-12","05PM").endswith("Injury-Report_2023-01-12_05PM.pdf")
    a=parse_nominal("2023-11-15","05PM")
    assert a.hour==22 and a.tzinfo==timezone.utc
    b=parse_nominal("2024-01-12","05PM")
    assert b.hour==22 and b.tzinfo==timezone.utc
    try:url_for("2023-01-12","../")
    except ValueError:pass
    else:raise AssertionError("UNSAFE_URL")
    print("NBA_LEGACY_OFFICIAL_ARCHIVE_PROBE_TEST_PASS")

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--out",default="nba-legacy-injury-archive-audit.json")
    p.add_argument("--self-test",action="store_true")
    args=p.parse_args()
    if args.self_test:self_test()
    else:run(args.out)
