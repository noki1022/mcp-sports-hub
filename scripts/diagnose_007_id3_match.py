#!/usr/bin/env python3
"""Read-only 007 scoreboard/ID3 market diagnostics, no invented prices."""
import json,argparse,hashlib
from collections import Counter
from datetime import datetime,timedelta,timezone
from xml.etree import ElementTree as ET
from pathlib import Path
from urllib.parse import urlencode
from titan007_join_beijing_verified import (SOURCE_BASE,public_get,identify,market_entries,
    fetch_schedule,matchup_key,accept_match,num)

def breakdown(raw):
    root=ET.fromstring(raw.decode("gb18030","replace").lstrip("\ufeff"))
    result={};counts=Counter()
    for el in root.findall(".//match/m"):
        cells=(el.text or "").split(",")
        if not cells or not cells[0].isdigit():counts["INVALID_ID"]+=1;continue
        ident=cells[0]
        if ident in result:counts["DUPLICATE_ID"]+=1;continue
        spread=len(cells)>=4 and all(num(cells[i],low,high)is not None for i,low,high in ((1,-80,80),(2,0.001,9),(3,0.001,9)))
        total=len(cells)>=7 and all(num(cells[i],low,high)is not None for i,low,high in ((4,80,400),(5,0.001,9),(6,0.001,9)))
        state="BOTH_VALID" if spread and total else "SPREAD_ONLY" if spread else "TOTAL_ONLY" if total else "INVALID_BOTH"
        result[ident]={"status":state,"fields":len(cells)}
        counts[state]+=1
    return result,dict(counts)

def run(target):
    fixtures,_=fetch_schedule(target)
    out={"schema":"007-id3-exact-match-diagnostics-v1","target_date":target,"started_at_utc":datetime.now(timezone.utc).isoformat(),"games":{},"captures":[]}
    for f in fixtures:
        out["games"][str(f["nba_game_id"])]={"home":f["home"],"away":f["away"],"tip":f["beijing_tip"],"checks":[]}
    for shift in (-1,0,1):
        day=(datetime.fromisoformat(target)+timedelta(days=shift)).date().isoformat()
        for hour in (0,12):
            args={"date":day,"h":str(hour),"m":"00"}
            score_url=SOURCE_BASE+"nba_date.aspx?"+urlencode(dict(args,s="1"))
            odds_url=SOURCE_BASE+"nba_Oddsdata.aspx?"+urlencode(dict(args,id="3"))
            row={"date":day,"h":hour,"at_utc":datetime.now(timezone.utc).isoformat()}
            try:
                s=public_get(score_url,limit=700000);o=public_get(odds_url,limit=250000)
                identities,rejected=identify(s)
                parsed,parse_rejected=market_entries(o)
                raw,states=breakdown(o)
                row.update(score_hash=hashlib.sha256(s).hexdigest(),odds_hash=hashlib.sha256(o).hexdigest(),
                    scoreboard=len(identities),nba=sum(v["league"]=="NBA" for v in identities.values()),
                    odds_raw=len(raw),odds_any_verified=len(parsed),status=states,
                    rejected_score=len(rejected),rejected_odds=parse_rejected,
                    id_intersection=len(set(identities)&set(raw)))
                for f in fixtures:
                    matches=[(mid,g) for mid,g in identities.items() if g["league"]=="NBA" and matchup_key(g["home_team"],g["away_team"])==(f["home"],f["away"])]
                    out["games"][str(f["nba_game_id"])]["checks"].append({"date":day,"h":hour,"candidates":[{
                        "id":mid,"site_date":g["display_date"],"site_time":g["display_clock"],
                        "identity_match":accept_match(g,f,g["display_date"],g["display_clock"]),
                        "raw_market":raw.get(mid),"strict_market":mid in parsed} for mid,g in matches]})
            except (ValueError,OSError,RuntimeError,ET.ParseError) as exc:
                row["error"]=type(exc).__name__+": "+str(exc)[:160]
            out["captures"].append(row)
            print("ID3_FORENSIC",json.dumps(row,ensure_ascii=False),flush=True)
    return out

def test():
    xml=b'<c><match><m>10001,1.5,0.90,0.90,225.5,,0.92</m><m>10002,,0.9,0.9,229.5,0.9,0.9</m><m>10003,2.5,0.9,0.9,230.5,0.9,0.9</m></match></c>'
    raw,states=breakdown(xml)
    assert raw["10001"]["status"]=="SPREAD_ONLY"
    assert raw["10002"]["status"]=="TOTAL_ONLY"
    assert raw["10003"]["status"]=="BOTH_VALID"
    assert len(market_entries(xml)[0])==3
    print("ID3_FORENSIC_SELFTEST_PASS")

if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--target",default="2026-11-01")
    p.add_argument("--out",default="007-id3-forensics.json");p.add_argument("--self-test",action="store_true")
    a=p.parse_args()
    if a.self_test:test()
    else:
        result=run(a.target)
        Path(a.out).write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
        print("ID3_FORENSICS_COMPLETE",len(result["captures"]),len(result["games"]))
