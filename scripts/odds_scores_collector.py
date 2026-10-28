#!/usr/bin/env python3
"""Fetch completed NBA scores using an injected The Odds API key.

The key is never printed. This is a collector only; settlement remains offline
and rejects ambiguous event/team/time joins.
"""
import json, os, urllib.parse, urllib.request
from datetime import datetime, timezone
from pathlib import Path

def fetch_scores(days_from=3):
    key=(os.getenv("THE_ODDS_API_KEY") or os.getenv("ODDS_API_KEY") or os.getenv("ODD"))
    if not key: raise RuntimeError("Odds API key is not configured")
    q=urllib.parse.urlencode({"apiKey":key,"daysFrom":days_from,"dateFormat":"iso"})
    url="https://api.the-odds-api.com/v4/sports/basketball_nba/scores/?"+q
    req=urllib.request.Request(url,headers={"User-Agent":"mcp-sports-hub/settlement"})
    with urllib.request.urlopen(req,timeout=30) as r:
        return json.loads(r.read().decode())

def normalize(e):
    scores=e.get("scores") or []
    parsed={s.get("name"):float(s["score"]) for s in scores if s.get("name") and s.get("score") is not None}
    return {"event_id":e.get("id"),"sport_key":e.get("sport_key"),
            "commence_time":e.get("commence_time"),"completed":bool(e.get("completed")),
            "home_team":e.get("home_team"),"away_team":e.get("away_team"),
            "home_points":parsed.get(e.get("home_team")),"away_points":parsed.get(e.get("away_team")),
            "captured_at":datetime.now(timezone.utc).isoformat()}

if __name__=="__main__":
    out=Path(os.getenv("ODDS_SCORES_OUT","data/results/odds_api_scores.json")); out.parent.mkdir(parents=True,exist_ok=True)
    rows=[normalize(e) for e in fetch_scores()]
    out.write_text(json.dumps({"source":"The Odds API","captured_at":datetime.now(timezone.utc).isoformat(),"games":rows},ensure_ascii=False,indent=2))
    print(json.dumps({"completed_games":sum(x["completed"] for x in rows),"rows":len(rows),"output":str(out)}))
