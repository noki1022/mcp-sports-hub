#!/usr/bin/env python3
"""Check reproducible season-end NBA injury archive and matched player logs.

This is an audit. Never treat report_datetime's nominal file timestamp as
proof the publisher made a report available at exactly that instant.
"""
from pathlib import Path
import json,hashlib,urllib.request
import pandas as pd
ROOT=Path('/tmp/nba-real-injury');ROOT.mkdir(exist_ok=True)
URLS={
"in2025":"https://github.com/sportsdataverse/sportsdataverse-data/releases/download/nba_stats_injury_report/injury_report_2025.parquet",
"in2026":"https://github.com/sportsdataverse/sportsdataverse-data/releases/download/nba_stats_injury_report/injury_report_2026.parquet",
"pl2025":"https://raw.githubusercontent.com/xtheredshirtx/fanduel-player-data/main/NBA/csv/NBA_players_game_log_2024-25_as_of_2026-10-31.csv",
"pl2026":"https://raw.githubusercontent.com/xtheredshirtx/fanduel-player-data/main/NBA/csv/NBA_players_game_log_2025-26_as_of_2026-10-31.csv"
}
res={"stage":"2024-25_fit_to_2025-26_independent_holdout_source_probe","files":{}}
for key,url in URLS.items():
    req=urllib.request.Request(url,headers={"User-Agent":"NBA-PIT-Injury-Study/1.0"})
    with urllib.request.urlopen(req,timeout=55) as response:
        raw=response.read(5000001)
    if len(raw)>5000000 or len(raw)<1000:raise RuntimeError("WRONG_FILE_SIZE_"+key)
    p=ROOT/(key+(".parquet" if key.startswith("in") else ".csv"));p.write_bytes(raw)
    data=pd.read_parquet(p) if key.startswith("in") else pd.read_csv(p,low_memory=False)
    info={"sha256":hashlib.sha256(raw).hexdigest(),"source_url":url,
          "rows":len(data),"columns":list(data.columns)}
    for col in ("game_date","report_datetime","Date","report_matchup","current_status","player_name"):
        if col in data.columns:info[col+"_sample"]=[str(x) for x in data[col].dropna().head(2)]
    if "game_date" in data:
        info["first_game"]=str(data["game_date"].min());info["last_game"]=str(data["game_date"].max())
        info["distinct_game_dates"]=int(data["game_date"].nunique())
    if key.startswith("in"):
        info["sample_full_rows"]=[{k:str(v) for k,v in r.items()} for r in data.head(2).to_dict(orient="records")]
    res["files"][key]=info
    print("SCHEMA",key,json.dumps(info,ensure_ascii=False))
Path("nba-real-injury-schema-audit.json").write_text(json.dumps(res,indent=2,ensure_ascii=False))
