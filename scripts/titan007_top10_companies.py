#!/usr/bin/env python3
"""Best-effort top-ten DISPLAYED bookmaker rows from public Titan007 basketball pages.
NO invented IDs, labels, water orientation, or bookmaker odds timestamps.
"""
import argparse,html,json,re,time,urllib.request,urllib.robotparser
from datetime import datetime,timedelta,timezone
from pathlib import Path
from statistics import median
from html.parser import HTMLParser

HOST="https://m.titan007.com"
UA="Titan007BasketballResearch/1.0"
NUM=re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$")
class Parser(HTMLParser):
    def __init__(self):super().__init__();self.rows=[];self.row=None;self.cell=None
    def handle_starttag(self,t,a):
        if t=="tr":self.row={"cells":[],"attrs":dict(a),"text":""}
        if self.row is not None and t in ("td","th"):self.cell=[]
    def handle_data(self,d):
        if self.row is not None:self.row["text"]+=d
        if self.cell is not None:self.cell.append(d)
    def handle_endtag(self,t):
        if t in ("td","th") and self.row is not None and self.cell is not None:
            self.row["cells"].append(html.unescape("".join(self.cell)).strip());self.cell=None
        if t=="tr" and self.row is not None:self.rows.append(self.row);self.row=None;self.cell=None
def extract(markup,market,limit=10):
    p=Parser();p.feed(markup)
    found=[];seen=set()
    for r in p.rows:
        cells=r["cells"]
        # Require exactly two sets of HK first/line/second values and a visible company label.
        if len(cells)<7:continue
        vals=[x.replace(" ","") for x in cells]
        nums=[float(x) for x in vals if NUM.fullmatch(x)]
        if len(nums)!=6:continue
        labels=[x for x in cells if x and not NUM.fullmatch(x.replace(" ",""))]
        if not labels:continue
        name=labels[0][:48]
        if not name or name in seen:continue
        seen.add(name)
        found.append({"display_rank":len(found)+1,"company_display":name,
            "company_id":"UNVERIFIED","market":market,
            "opening":{"first_side_water":nums[0],"line":nums[1],"second_side_water":nums[2]},
            "current":{"first_side_water":nums[3],"line":nums[4],"second_side_water":nums[5]},
            "side_orientation":"UNVERIFIED_RAW_SLOTS","source":"VISIBLE_TABLE_ROW"})
        if len(found)==limit:break
    return found
def allowed(url):
    rp=urllib.robotparser.RobotFileParser()
    req=urllib.request.Request(HOST+"/robots.txt",headers={"User-Agent":UA})
    with urllib.request.urlopen(req,timeout=8) as r:rp.parse(r.read(50000).decode("utf-8","replace").splitlines())
    return rp.can_fetch(UA,url)
# Independently verified with real 007 dated odds on 2026-10-31.
# These are ten distinct SOURCE IDs, NOT a verified top-ten page ranking.
VALIDATED_SOURCE_IDS=("3","1","2","8","9","10","19","20","24","31")
def collect(board,limit=10):
    """Reuse the production Crown dated endpoint for ten distinct real company IDs."""
    import urllib.parse
    from titan007_join_daily import public_get
    from titan007_join_beijing_verified import market_entries
    target=board["requested_display_date"]
    selected=VALIDATED_SOURCE_IDS[:limit]
    ids={str(g["game_id"]):g for g in board.get("nba_cba_games",[]) if g.get("league")=="NBA"}
    bygame={gid:{"game_id":gid,"nba_game_id":str(g.get("nba_game_id")),
                  "markets":{k:{"status":"NO_QUOTE","companies":[],"source_id_order_unverified":True}
                             for k in ("full_spread","full_total")}} for gid,g in ids.items()}
    source_audit=[]
    # ID3 is the canonical Crown source already fetched by the verified
    # cross-date join. Reuse it rather than issuing a second target-date-only
    # request that can miss valid adjacent-date rows.
    canonical_count=0
    for gid,board_game in ids.items():
        for market in ("full_spread","full_total"):
            quote=((board_game.get("markets") or {}).get(market) or {})
            current=quote.get("current") or {}
            if (str(board_game.get("market_source_id") or "3")=="3"
                    and current.get("line") is not None
                    and current.get("first_side_water") is not None
                    and current.get("second_side_water") is not None):
                bygame[gid]["markets"][market]["companies"].append({
                    "display_rank":None,
                    "company_display":"皇冠（007机构ID 3）",
                    "company_id":"3","market":market,
                    "opening":quote.get("opening") or {},
                    "current":current,
                    "side_orientation":"UNVERIFIED_RAW_SLOTS",
                    "source":"DATED_007_COMPANY_ID",
                    "source_capture_utc":board.get("crown_quote_captured_at_utc") or board.get("captured_at_utc")})
                canonical_count+=1
    source_audit.append({"id":"3","url":"https://bf.titan007.com/nba_Oddsdata.aspx?id=3",
        "status":"REUSED_CANONICAL_CROSS_DATE_JOIN","matched_games":len({
            gid for gid,item in bygame.items()
            if any(c.get("company_id")=="3" for market in item["markets"].values()
                   for c in market["companies"])}),
        "verified_market_rows":canonical_count})
    # Query target and adjacent 007 site dates; Beijing display date is not
    # assumed identical to the source-date bucket. Join only exact verified IDs.
    query_dates=[(datetime.fromisoformat(target)+timedelta(days=offset)).date().isoformat()
                 for offset in (0,-1,1)]
    for cid in selected:
        if cid=="3":
            continue
        status={"id":cid,"url":None,"status":"UNAVAILABLE","matched_games":0,
                "query_dates":query_dates,"source_rows":0,"verified_market_rows":0,
                "rejections":{},"query_capture_utc":[]}
        chosen={}
        matched=set()
        for day in query_dates:
            url="https://bf.titan007.com/nba_Oddsdata.aspx?"+urllib.parse.urlencode(
                {"date":day,"id":cid,"h":"12","m":"00"})
            if status["url"] is None:status["url"]=url
            try:
                raw=public_get(url,limit=250000)
                source_capture_utc=datetime.now(timezone.utc).isoformat()
                status["query_capture_utc"].append({"date":day,"captured_at_utc":source_capture_utc})
                quotes,reject=market_entries(raw)
                status["source_rows"]+=len(quotes)
                for reason,count in reject.items():
                    status["rejections"][reason]=status["rejections"].get(reason,0)+count
                for gid in ids:
                    quote=quotes.get(gid)
                    if quote is None:continue
                    matched.add(gid)
                    for market in ("full_spread","full_total"):
                        m=quote[market]
                        current=m.get("current") or {}
                        if not all(current.get(k) is not None for k in ("line","first_side_water","second_side_water")):continue
                        key=(gid,market)
                        candidate={"display_rank":None,
                            "company_display":"007机构ID "+cid+"（名称待核）",
                            "company_id":cid,"market":market,
                            "opening":m.get("opening") or {},"current":current,
                            "side_orientation":"UNVERIFIED_RAW_SLOTS",
                            "source":"DATED_007_COMPANY_ID",
                            "source_capture_utc":source_capture_utc,"source_query_date":day}
                        previous=chosen.get(key)
                        if previous is None or candidate["source_capture_utc"]>previous["source_capture_utc"]:
                            chosen[key]=candidate
            except (OSError,ValueError,RuntimeError) as exc:
                reason="QUERY_"+type(exc).__name__
                status["rejections"][reason]=status["rejections"].get(reason,0)+1
                status.setdefault("query_errors",[]).append({"date":day,"error":type(exc).__name__+": "+str(exc)[:105]})
        for (gid,market),candidate in chosen.items():
            bygame[gid]["markets"][market]["companies"].append(candidate)
            status["verified_market_rows"]+=1
        status["matched_games"]=len(matched)
        status["status"]="PARSED" if status["source_rows"] else "NO_ROWS"
        source_audit.append(status)
    collection_completed_at_utc=datetime.now(timezone.utc).isoformat()
    for src in bygame.values():
        for market,item in src["markets"].items():
            item["status"]="QUOTES_WITH_UNVERIFIED_COMPANY_RANK" if item["companies"] else "NO_VERIFIED_QUOTE"
            item["company_ids"]=[c["company_id"] for c in item["companies"]]
    return {"schema_version":"nba-007-visible-top10-v1",
        "target_date":target,"captured_at_utc":board["captured_at_utc"],
        "collection_completed_at_utc":collection_completed_at_utc,
        "quote_timestamp":"PER_SOURCE_CAPTURE_TIME_RECORDED","company_order":"TEN_VALIDATED_SOURCE_IDS_NOT_TOP_TEN_RANKED",
        "candidate_ids":list(selected),"source_audit":source_audit,
        "games":list(bygame.values()),"model_probability_adjusted":False,"decision":"NO_BET"}

def load_json_legacy(path):
    """Read genuine stored 007 snapshots, including legacy literal-backslash-n suffix."""
    raw=Path(path).read_text(encoding="utf-8").strip()
    if raw.endswith("\\n"):
        raw=raw[:-2]
    return json.loads(raw)

def recover_crown_id3(root,target,current_capture,tipoffs):
    """Latest real, pre-tip ID 3 line for each game/market from same-date archives.

    Never uses another company or invents current odds. The prior snapshot
    timestamp is frozen and explicitly displayed as OLD/NOT-LIVE downstream.
    """
    result={}
    if root is None or not root.is_dir():return result
    current=datetime.fromisoformat(str(current_capture).replace("Z","+00:00"))
    if current.tzinfo is None:raise ValueError("CAPTURE_TIMEZONE_REQUIRED")
    for path in root.glob("*.json"):
        try:
            snap=load_json_legacy(path)
            if snap.get("schema_version")!="nba-007-visible-top10-v1" or snap.get("target_date")!=target:
                continue
            stamp=datetime.fromisoformat(str(snap["captured_at_utc"]).replace("Z","+00:00"))
            if stamp.tzinfo is None or stamp>=current:continue
            for game in snap.get("games",[]):
                gid=str(game.get("game_id") or "")
                tip=tipoffs.get(gid)
                if tip is None or stamp>=tip:continue
                for kind in ("full_spread","full_total"):
                    item=(game.get("markets") or {}).get(kind) or {}
                    for quote in item.get("companies",[]):
                        if str(quote.get("company_id"))!="3" or quote.get("source")!="DATED_007_COMPANY_ID":
                            continue
                        values=quote.get("current") or {}
                        if any(not isinstance(values.get(key),(float,int)) or
                               isinstance(values.get(key),bool) or
                               not (-1000<float(values[key])<1000)
                               for key in ("line","first_side_water","second_side_water")):
                            continue
                        key=(gid,kind)
                        if key not in result or stamp>result[key][0]:
                            result[key]=(stamp,quote)
        except (ValueError,TypeError,KeyError,OSError):
            continue
    recovered={}
    for key,(stamp,quote) in result.items():
        row=dict(quote)
        row["source"]="DATED_007_COMPANY_ID_ARCHIVED_PRETIP"
        row["observed_capture_utc"]=stamp.isoformat()
        row["quote_freshness"]="ARCHIVED_PRIOR_NOT_LIVE"
        recovered[key]=row
    return recovered

def analyze(current,prior,recovery=None):
    past={str(g["game_id"]):g for g in prior.get("games",[])} if prior else {}
    rows=[]
    for g in current.get("games",[]):
        markets={}
        for k,m in g["markets"].items():
            fresh=m.get("companies",[])
            companies=list(fresh)
            has_live_id3=any(str(c.get("company_id"))=="3" and
                             c.get("source")=="DATED_007_COMPANY_ID" for c in fresh)
            recovered=(recovery or {}).get((str(g["game_id"]),k))
            if not has_live_id3 and recovered:
                companies.append(recovered)
            # Aggregated range/median must contain only current quotes, not fallback.
            lines=[float(r["current"]["line"]) for r in fresh]
            previous=(past.get(g["game_id"],{}).get("markets") or {}).get(k,{})
            # The archived Crown ID3 quote can be a valid pre-tip observation
            # without legacy display metadata; never let a label break delivery.
            # Prefer a known institution ID, else a nonempty display name.
            def company_key(row):
                company_id=str(row.get("company_id") or "")
                if company_id.isdigit():
                    return ("007_ID",company_id)
                label=row.get("company_display")
                return ("DISPLAY",label) if isinstance(label,str) and label.strip() else None
            byname={key:x for x in previous.get("companies",[])
                    if (key:=company_key(x)) is not None}
            delta=[]
            for c in companies:
                key=company_key(c)
                old=byname.get(key) if key is not None else None
                if old is not None:
                    delta.append({"company":c.get("company_display") or
                                 "007机构ID "+str(c.get("company_id","未核")),
                                  "delta_line":round(c["current"]["line"]-old["current"]["line"],3)})
            markets[k]={"status":("ARCHIVED_PRETIP_CROWN_FALLBACK" if recovered and not has_live_id3 else m["status"]),
               "company_count":len(fresh),"crown_id3_archived":bool(recovered and not has_live_id3),
               "median_line":median(lines) if lines else None,
               "line_min":min(lines) if lines else None,"line_max":max(lines) if lines else None,
               "last_capture_company_changes":delta,
               "companies":companies,"reason":m.get("reason")}
        rows.append({"game_id":g["game_id"],"markets":markets})
    return {"schema_version":"nba-007-top10-comparison-v1",
        "target_date":current["target_date"],"captured_at_utc":current["captured_at_utc"],
        "games":rows,"decision":"NO_BET","model_probability_adjusted":False,
        "caveat":"Ten independently tested company ID feeds; source company names and page top-ten ranking remain UNVERIFIED. These are candidate sources, not authenticated top-ten ranking."}
def selftest():
    global VALIDATED_SOURCE_IDS
    raw="<table>"+''.join(f"<tr><td>机构{i}</td><td>0.90</td><td>220.5</td><td>0.92</td><td>0.88</td><td>{220.5+i}</td><td>0.94</td></tr>" for i in range(12))+"</table>"
    x=extract(raw,"full_total")
    assert len(x)==10 and x[0]["company_display"]=="机构0" and x[-1]["display_rank"]==10
    assert x[0]["company_id"]=="UNVERIFIED"
    o=analyze({"target_date":"2026-10-31","captured_at_utc":"2026-10-30T08:00:00Z","games":[{"game_id":"1234","markets":{"full_total":{"status":"PARSED_VISIBLE_ROWS","companies":x}}}]},None)
    assert o["games"][0]["markets"]["full_total"]["company_count"]==10
    assert not o["model_probability_adjusted"]
    assert len(VALIDATED_SOURCE_IDS)==10 and len(set(VALIDATED_SOURCE_IDS))==10
    # The canonical Crown ID3 quote must be reused without a second network
    # request, even when the institution comparison is restricted to ID3.
    original_ids=VALIDATED_SOURCE_IDS
    VALIDATED_SOURCE_IDS=("3",)
    try:
        board={"requested_display_date":"2026-10-31",
          "captured_at_utc":"2026-10-30T14:00:00Z",
          "crown_quote_captured_at_utc":"2026-10-30T14:00:00Z",
          "nba_cba_games":[{"game_id":"1234","nba_game_id":"nba1234","league":"NBA",
            "home_team":"主队","away_team":"客队","market_source_id":"3",
            "markets":{"full_spread":{"current":{"line":-5.5,"first_side_water":0.9,"second_side_water":0.95}},
                       "full_total":{"current":{"line":224.5,"first_side_water":0.92,"second_side_water":0.94}}}}]}
        canonical=collect(board)
    finally:
        VALIDATED_SOURCE_IDS=original_ids
    assert canonical["source_audit"][0]["status"]=="REUSED_CANONICAL_CROSS_DATE_JOIN"
    assert canonical["source_audit"][0]["verified_market_rows"]==2
    for market in ("full_spread","full_total"):
        row=canonical["games"][0]["markets"][market]["companies"][0]
        assert row["company_id"]=="3" and row["source"]=="DATED_007_COMPANY_ID"
        assert row["source_capture_utc"]=="2026-10-30T14:00:00Z"
    assert canonical["collection_completed_at_utc"]
    import tempfile
    with tempfile.TemporaryDirectory() as scratch:
        folder=Path(scratch)
        archive={"schema_version":"nba-007-visible-top10-v1",
            "target_date":"2026-10-31","captured_at_utc":"2026-10-30T15:30:00Z",
            "games":[{"game_id":"728165","markets":{}}]}
        for market,line in (("full_spread",-1.5),("full_total",219.5)):
            archive["games"][0]["markets"][market]={"companies":[{
                "company_id":"3","source":"DATED_007_COMPANY_ID",
                "current":{"line":line,"first_side_water":0.9,"second_side_water":0.95}}]}
        (folder/"old.json").write_text(json.dumps(archive)+"\\n")
        tips={"728165":datetime.fromisoformat("2026-10-31T07:00:00+08:00")}
        saved=recover_crown_id3(folder,"2026-10-31","2026-10-30T17:30:00Z",tips)
        assert saved[("728165","full_spread")]["current"]["line"]==-1.5
        assert saved[("728165","full_total")]["current"]["line"]==219.5
        assert all(q["company_id"]=="3" for q in saved.values())
        assert all(q["quote_freshness"]=="ARCHIVED_PRIOR_NOT_LIVE" for q in saved.values())
        assert not recover_crown_id3(folder,"2026-10-30","2026-10-30T17:30:00Z",tips)
        assert not recover_crown_id3(folder,"2026-10-31","2026-10-30T15:00:00Z",tips)
        assert not recover_crown_id3(folder,"2026-10-31","2026-10-30T17:30:00Z",
            {"728165":datetime.fromisoformat("2026-10-30T14:00:00Z")})
        current={"target_date":"2026-10-31","captured_at_utc":"2026-10-30T17:30:00Z",
          "games":[{"game_id":"728165","markets":{
            "full_spread":{"status":"NO_VERIFIED_QUOTE","companies":[]},
            "full_total":{"status":"NO_VERIFIED_QUOTE","companies":[]}}}]}
        rebuilt=analyze(current,{},saved)
        assert rebuilt["games"][0]["markets"]["full_spread"]["crown_id3_archived"]
        assert rebuilt["games"][0]["markets"]["full_total"]["companies"][0]["company_id"]=="3"
        assert rebuilt["games"][0]["markets"]["full_total"]["company_count"]==0
    print("TITAN007_TOP10_NO_INVENTED_COMPANY_TEST_PASS")
if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--joined");p.add_argument("--out");p.add_argument("--analysis")
    p.add_argument("--previous");p.add_argument("--history-root");p.add_argument("--self-test",action="store_true");a=p.parse_args()
    if a.self_test:selftest()
    else:
        if not a.joined or not a.out or not a.analysis:raise SystemExit("MISSING_REQUIRED_ARGUMENTS")
        board=json.loads(Path(a.joined).read_text());snap=collect(board)
        older=Path(a.previous) if a.previous else None
        if a.history_root:
            root=Path(a.history_root)/snap["target_date"]
            root.mkdir(parents=True,exist_ok=True)
            existing=[]
            for file in root.glob("*.json"):
                try:
                    old=json.loads(file.read_text())
                    if old.get("schema_version")!="nba-007-visible-top10-v1":continue
                    if old.get("target_date")!=snap["target_date"]:continue
                    if old.get("captured_at_utc","")>=snap["captured_at_utc"]:continue
                    existing.append((old["captured_at_utc"],file))
                except (OSError,ValueError,TypeError,KeyError):continue
            if existing:older=max(existing)[1]
        try:prior=load_json_legacy(older) if older and older.is_file() else {}
        except (ValueError,OSError):prior={}
        tips={}
        for item in board.get("nba_cba_games",[]):
            try:
                tip=datetime.fromisoformat(str(item["start_time_beijing"]).replace("Z","+00:00"))
                if tip.tzinfo is not None:tips[str(item["game_id"])]=tip
            except (KeyError,TypeError,ValueError):continue
        recovery=recover_crown_id3(
            Path(a.history_root)/snap["target_date"] if a.history_root else None,
            snap["target_date"],snap["captured_at_utc"],tips)
        Path(a.out).write_text(json.dumps(snap,ensure_ascii=False,indent=2)+"\n")
        Path(a.analysis).write_text(json.dumps(analyze(snap,prior,recovery),ensure_ascii=False,indent=2)+"\n")
        if a.history_root:
            filename=snap["captured_at_utc"].replace(":","-").replace("+","_")+".json"
            (root/filename).write_text(json.dumps(snap,ensure_ascii=False,indent=2)+"\n")
        print("NBA_TOP10_007",len(snap["games"]))
