#!/usr/bin/env python3
"""Cross-audit Kaggle NBA odds ZIP against historical match keys, without storage."""
import csv,io,zipfile,json,hashlib
from collections import Counter,defaultdict
from urllib.request import Request,urlopen
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"analysis"))
from sbr_archive_import import canonical_team
from nba_archive_crosscheck import bounded_fetch,LINE_SHEET,score_row
ABBR={"sa":"SAS","gs":"GSW","utah":"UTA","wsh":"WAS","ny":"NYK","no":"NOP","nj":"BKN","pho":"PHX","phx":"PHX","okc":"OKC","lac":"LAC","lal":"LAL","por":"POR","tor":"TOR","phi":"PHI","ind":"IND","hou":"HOU","atl":"ATL","bos":"BOS","bkn":"BKN","brk":"BKN","cha":"CHA","chi":"CHI","cle":"CLE","dal":"DAL","den":"DEN","det":"DET","mem":"MEM","mia":"MIA","mil":"MIL","min":"MIN","nop":"NOP","orl":"ORL","sac":"SAC","sea":"SEA","sas":"SAS","uta":"UTA","was":"WAS"}
def norm(x):
    return ABBR.get(str(x).strip().lower()) or canonical_team(x)
URL="https://www.kaggle.com/api/v1/datasets/download/cviaxmiwnptr/nba-betting-data-october-2007-to-june-2024"
def main():
    with urlopen(Request(URL,headers={"User-Agent":"nba-integrity-audit/1.0"}),timeout=35) as r: blob=r.read(6000001)
    if len(blob)>6000000 or not zipfile.is_zipfile(io.BytesIO(blob)):raise RuntimeError("BOUNDED_ZIP_REJECTED")
    reference=defaultdict(set)
    for x in csv.DictReader(io.StringIO(bounded_fetch(LINE_SHEET).decode("utf-8-sig"))):
        try:
            g=score_row(x)
            reference[g["key"]].add((g["home_points"],g["away_points"]))
        except (ValueError,KeyError,TypeError):pass
    z=zipfile.ZipFile(io.BytesIO(blob))
    names=[n for n in z.namelist() if n.endswith(".csv")]
    if len(names)!=1:raise RuntimeError("UNEXPECTED_CSV_FILE_COUNT")
    counts=Counter();seen=defaultdict(list); date_examples=[]; team_examples=[]; errors=Counter()
    with z.open(names[0]) as f:
        reader=csv.DictReader(io.TextIOWrapper(f,encoding="utf-8-sig",newline=""))
        needed={"date","home","away","score_home","score_away","spread","total","moneyline_home","moneyline_away"}
        if not needed.issubset(reader.fieldnames or []):raise RuntimeError("MISSING_REQUIRED_COLUMNS")
        for r in reader:
            counts["raw_rows"]+=1
            try:
                d=r["date"].strip()
                if len(date_examples)<5:date_examples.append(d)
                if len(team_examples)<5:team_examples.append([r["home"],r["away"],r["score_home"],r["score_away"],r["total"]])
                from datetime import datetime
                from datetime import date as Date
                try:day=datetime.fromisoformat(d.replace("Z","+00:00")).date().isoformat()
                except ValueError:
                    try:day=datetime.strptime(d,"%m/%d/%Y").date().isoformat()
                    except ValueError:day=None
                home,away=norm(r["home"]),norm(r["away"])
                h,a=int(r["score_home"]),int(r["score_away"])
                if not day or not home or not away or home==away or not 40<=h<=200 or not 40<=a<=200 or h==a:raise ValueError("IDENTITY_OR_SCORE")
                if not all(0<float(r[x])<350 for x in ("total",)):raise ValueError("TOTAL_INVALID")
                key=(day,home,away)
                seen[key].append((h,a))
            except (ValueError,TypeError,KeyError,OverflowError) as e:
                errors[type(e).__name__+":"+str(e)[:50]]+=1
                counts["rejected_identity_score_or_total"]+=1
    for key,vals in seen.items():
        if len(vals)!=1:
            counts["duplicate_keys_excluded"]+=1
            continue
        result=reference.get(key)
        if result is None:
            counts["no_line_sheet_match"]+=1
        elif len(result)!=1 or next(iter(result))!=vals[0]:
            counts["conflicting_score_or_ref"]+=1
        else:
            counts["score_matched_candidate_only"]+=1
    print("KAGGLE_BETTING_CROSS_AUDIT "+json.dumps({"counts":dict(counts),"date_examples":date_examples,"team_examples":team_examples,"reject_details":dict(errors.most_common(7)),"source_sha256":hashlib.sha256(blob).hexdigest(),
      "no_quote_timestamp":True,"no_independent_provenance_proof":True,
      "not_training_approved":True,"raw_persisted":False},sort_keys=True))
if __name__=="__main__":main()
