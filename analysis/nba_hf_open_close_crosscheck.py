#!/usr/bin/env python3
"""Cross-validate open/close NBA consensus odds with independent score archive.

HF licensed 2024-25 season has UTC tip times and OPEN vs CLOSE *stages*,
but no quote publication timestamps. Do not retroactively assign a timestamp
to an open or close quote. Historical game-level odds modeling can use those
declared stages, but exact 2h/30m timing studies require true snapshots.
"""
from __future__ import annotations
import argparse,csv,hashlib,io,json,math
from collections import Counter,defaultdict
from datetime import datetime,timezone
from pathlib import Path
from urllib.request import Request,urlopen
from zoneinfo import ZoneInfo
import nba_historical_market_benchmark as B

URL=("https://huggingface.co/datasets/minmaxxxer/"
     "nba-closing-lines-ats-2024-25/resolve/main/"
     "nba_2024_25_closing_lines_ats.csv")
MAX_BYTES=600_000
FIELDS=("game_id","date_et","start_time_utc","home_team","away_team",
        "home_score","away_score","open_home_win_prob","close_home_win_prob",
        "open_spread_home","close_spread_home",
        "open_total","close_total","close_home_cover_prob","close_over_prob",
        "moneyline_winner","ats_result","ats_result_open",
        "total_result","total_result_open")

def fetch():
    req=Request(URL,headers={"User-Agent":"NBA-Historical-Cross-Source-Research/1.0"})
    with urlopen(req,timeout=35) as resp:
        data=resp.read(MAX_BYTES+1)
    if len(data)>MAX_BYTES or not data:
        raise RuntimeError("HUGGINGFACE_CSV_MISSING_OR_TOO_LARGE")
    return data

def parse_timestamp(s):
    try:
        d=datetime.fromisoformat(str(s).replace("Z","+00:00"))
        return d.astimezone(timezone.utc) if d.tzinfo is not None else None
    except (TypeError,ValueError):
        return None

def num(v):
    try:
        if v is None or str(v).strip()=="":return None
        q=float(v)
        return q if math.isfinite(q) else None
    except (TypeError,ValueError):return None

def integer(v):
    p=num(v)
    return int(p) if p is not None and p.is_integer() else None

def side(value):
    return "home" if value>0 else "away" if value<0 else "push"

def over_under(value):
    return "over" if value>0 else "under" if value<0 else "push"

def historical_index(rows):
    bykey={}
    ambiguous=set()
    for r in rows:
        key=(r["date"],r["home"],r["away"])
        if key in bykey:ambiguous.add(key)
        else:bykey[key]=r
    for key in ambiguous:bykey.pop(key,None)
    return bykey

def validate(row,history):
    required=all(row.get(k) not in (None,"") for k in FIELDS)
    if not required:return None,"REQUIRED_FIELDS_MISSING"
    stamp=parse_timestamp(row.get("start_time_utc"))
    if stamp is None:return None,"TIP_TIMESTAMP_MISSING"
    day=row.get("date_et")
    if not day or stamp.astimezone(ZoneInfo("America/New_York")).date().isoformat()!=day:
        return None,"EASTERN_START_DATE_MISMATCH"
    team_home=B.CANONICAL.get(row["home_team"])
    team_away=B.CANONICAL.get(row["away_team"])
    if not team_home or not team_away or team_home==team_away:
        return None,"UNKNOWN_TEAM"
    score_h=integer(row["home_score"]);score_a=integer(row["away_score"])
    if score_h is None or score_a is None or score_h<50 or score_a<50:
        return None,"BAD_FINAL_SCORE"
    same=history.get((day,team_home,team_away))
    if same is None:return None,"NOT_IN_INDEPENDENT_NBA_LINE_SHEET"
    if same["home_points"]!=score_h or same["away_points"]!=score_a:
        return None,"CROSS_SOURCE_SCORE_DISAGREEMENT"
    opening=num(row["open_home_win_prob"])
    close=num(row["close_home_win_prob"])
    cov=num(row["close_home_cover_prob"])
    over_prob=num(row["close_over_prob"])
    vals={"open_spread":num(row["open_spread_home"]),
          "close_spread":num(row["close_spread_home"]),
          "open_total":num(row["open_total"]),
          "close_total":num(row["close_total"])}
    if (any(x is None or not .005<=x<=.995
            for x in (opening,close,cov,over_prob)) or
        any(x is None for x in vals.values())):
        return None,"INVALID_MARKET_PROBABILITY_OR_LINE"
    if (any(abs(vals[x])>80 for x in ("open_spread","close_spread")) or
        any(not 150<=vals[x]<=400 for x in ("open_total","close_total"))):
        return None,"INVALID_MARKET_LINE_RANGE"
    margin=score_h-score_a
    total=score_h+score_a
    if row["moneyline_winner"]!=side(margin):
        return None,"PUBLISHED_MONEYLINE_GRADE_DISAGREEMENT"
    derived={
      "open_ats":side(margin+vals["open_spread"]),
      "close_ats":side(margin+vals["close_spread"]),
      "open_total_result":over_under(total-vals["open_total"]),
      "close_total_result":over_under(total-vals["close_total"])
    }
    supplied={"open_ats":row["ats_result_open"],
              "close_ats":row["ats_result"],
              "open_total_result":row["total_result_open"],
              "close_total_result":row["total_result"]}
    if derived!=supplied:
        return None,"PUBLISHED_SPREAD_OR_TOTAL_GRADE_DISAGREEMENT"
    record={
      "schema_version":"nba-crosschecked-open-close-consensus-2024-25-v1",
      "source_file":"hf_nba_2024_25_closing_lines_ats.csv",
      "external_game_id":row["game_id"],
      "date_et":day,
      "tipoff_utc":stamp.isoformat().replace("+00:00","Z"),
      "home_team":row["home_team"],"away_team":row["away_team"],
      "home":team_home,"away":team_away,
      "final_score_home":score_h,"final_score_away":score_a,
      "market_open_p_home_no_vig":opening,
      "market_close_p_home_no_vig":close,
      "market_open_spread_home":vals["open_spread"],
      "market_close_spread_home":vals["close_spread"],
      "market_open_total":vals["open_total"],
      "market_close_total":vals["close_total"],
      "market_close_p_home_cover_no_vig":cov,
      "market_close_p_over_no_vig":over_prob,
      "observed_home_win":int(margin>0),
      "observed_home_cover_open":int(derived["open_ats"]=="home") if derived["open_ats"]!="push" else None,
      "observed_home_cover_close":int(derived["close_ats"]=="home") if derived["close_ats"]!="push" else None,
      "observed_over_open":int(derived["open_total_result"]=="over") if derived["open_total_result"]!="push" else None,
      "observed_over_close":int(derived["close_total_result"]=="over") if derived["close_total_result"]!="push" else None,
      "spread_line_move_towards_home":round(vals["open_spread"]-vals["close_spread"],2),
      "total_line_movement":round(vals["close_total"]-vals["open_total"],2),
      "open_quote_published_before_game_source_claim":True,
      "open_quote_update_utc":None,
      "close_quote_update_utc":None,
      "bookmaker": "CROSS_BOOK_CONSENSUS",
      "cross_source_score_verified":True,
      "cross_source_team_date_verified":True,
      "exact_pregame_capture_time_eligible":False,
      "research_open_close_benchmark_eligible":True,
      "production_fusion_eligible":False,
    }
    return record,None

def transform(hf,independent_games):
    raw=hf.decode("utf-8-sig")
    rd=csv.DictReader(io.StringIO(raw))
    if rd.fieldnames is None or not set(FIELDS).issubset(rd.fieldnames):
        raise ValueError("HF_SOURCE_SCHEMA_CHANGED")
    reference=historical_index(independent_games)
    rejects=Counter()
    duplicates=set()
    accepted=[]
    n=0
    for r in rd:
        n+=1
        game_key=str(r.get("game_id") or "")
        if not game_key or game_key in duplicates:
            rejects["DUPLICATE_EXTERNAL_GAME_ID"]+=1
            continue
        duplicates.add(game_key)
        record,why=validate(r,reference)
        if why:rejects[why]+=1
        else:accepted.append(record)
    return accepted,{
      "source":URL,"license_as_published":"CC-BY-4.0",
      "source_sha256":hashlib.sha256(hf).hexdigest(),
      "source_rows":n,"crosschecked_games":len(accepted),
      "rejections":dict(rejects),
    }

def evaluation(data):
    if not data:return {}
    brier_open=sum((r["market_open_p_home_no_vig"]-r["observed_home_win"])**2 for r in data)/len(data)
    brier_close=sum((r["market_close_p_home_no_vig"]-r["observed_home_win"])**2 for r in data)/len(data)
    def brier_stage(prob,label):
        vals=[(r[prob],r[label]) for r in data if r[label] is not None]
        return {"sample_count":len(vals),
                "brier":sum((p-y)**2 for p,y in vals)/len(vals) if vals else None}
    return {
     "games":len(data),
     "home_moneyline_brier_open":brier_open,
     "home_moneyline_brier_close":brier_close,
     "closing_minus_opening_brier":brier_close-brier_open,
     "home_cover_close_brier":brier_stage("market_close_p_home_cover_no_vig","observed_home_cover_close"),
     "over_close_brier":brier_stage("market_close_p_over_no_vig","observed_over_close"),
     "spread_changed":sum(abs(r["spread_line_move_towards_home"])>1e-9 for r in data),
     "total_changed":sum(abs(r["total_line_movement"])>1e-9 for r in data),
     "distinct_eastern_dates":len({r["date_et"] for r in data}),
    }

def run(out):
    base_rows, base_manifest=B.transform(B.fetch())
    data,meta=transform(fetch(),base_rows)
    metrics=evaluation(data)
    report={**meta,"evaluation":metrics,
      "independent_score_reference_sha256":base_manifest["source_sha256"],
      "source_tipoff_utc_observed":True,
      "actual_odds_quote_update_utc_available":False,
      "open_close_semantics":"PUBLISHED_SOURCE_STAGE_NOT_EXACT_TIMESTAMP",
      "production_promotion_allowed":False,
      "no_007_or_crown_price_substitution":True,
    }
    target=Path(out);target.mkdir(parents=True,exist_ok=True)
    (target/"manifest.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
    with (target/"crosschecked_2024_25_open_close_market.jsonl").open("w") as f:
        for r in data:
            f.write(json.dumps(r,ensure_ascii=False,sort_keys=True)+"\n")
    print("NBA_INDEPENDENT_CROSSCHECK_OPEN_CLOSE",json.dumps(report,ensure_ascii=False)[:16000])
    return report

def selftest():
    assert side(-2)=="away" and side(0)=="push"
    assert over_under(1)=="over" and over_under(-1)=="under"
    assert parse_timestamp("2024-10-22T23:30:00Z") is not None
    print("NBA_HF_OPEN_CLOSE_CROSS_SOURCE_SELFTEST_PASS")

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--self-test",action="store_true")
    p.add_argument("--out",default="/tmp/nba-open-close-crosschecked")
    args=p.parse_args()
    if args.self_test:selftest()
    else:run(args.out)
