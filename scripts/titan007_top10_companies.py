#!/usr/bin/env python3
"""Best-effort top-ten DISPLAYED bookmaker rows from public Titan007 basketball pages.
NO invented IDs, labels, water orientation, or bookmaker odds timestamps.
"""
import argparse,html,json,re,time,urllib.request,urllib.robotparser
from datetime import datetime,timezone
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
    for cid in selected:
        url="https://bf.titan007.com/nba_Oddsdata.aspx?"+urllib.parse.urlencode(
            {"date":target,"id":cid,"h":"12","m":"00"})
        status={"id":cid,"url":url,"status":"UNAVAILABLE","matched_games":0}
        try:
            raw=public_get(url,limit=250000)
            quotes,reject=market_entries(raw)
            status.update(status="PARSED","source_rows":len(quotes),"rejections":reject,
                          "matched_games":sum(gid in quotes for gid in ids))
            for gid,src in bygame.items():
                quote=quotes.get(gid)
                if quote is None:continue
                for market in ("full_spread","full_total"):
                    m=quote[market]
                    if not all(m["current"].get(k) is not None
                               for k in ("line","first_side_water","second_side_water")):continue
                    src["markets"][market]["companies"].append({
                        "display_rank":None,
                        "company_display":"007机构ID "+cid+"（名称待核）",
                        "company_id":cid,"market":market,
                        "opening":m.get("opening") or {},
                        "current":m["current"],"side_orientation":"UNVERIFIED_RAW_SLOTS",
                        "source":"DATED_007_COMPANY_ID"})
        except (OSError,ValueError,RuntimeError) as exc:
            status["error"]=type(exc).__name__+": "+str(exc)[:105]
        source_audit.append(status)
    for src in bygame.values():
        for market,item in src["markets"].items():
            item["status"]="QUOTES_WITH_UNVERIFIED_COMPANY_RANK" if item["companies"] else "NO_VERIFIED_QUOTE"
            item["company_ids"]=[c["company_id"] for c in item["companies"]]
    return {"schema_version":"nba-007-visible-top10-v1",
        "target_date":target,"captured_at_utc":board["captured_at_utc"],
        "quote_timestamp":"NOT_VERIFIED","company_order":"TEN_VALIDATED_SOURCE_IDS_NOT_TOP_TEN_RANKED",
        "candidate_ids":list(selected),"source_audit":source_audit,
        "games":list(bygame.values()),"model_probability_adjusted":False,"decision":"NO_BET"}

def analyze(current,prior):
    past={str(g["game_id"]):g for g in prior.get("games",[])} if prior else {}
    rows=[]
    for g in current.get("games",[]):
        markets={}
        for k,m in g["markets"].items():
            companies=m.get("companies",[])
            lines=[float(r["current"]["line"]) for r in companies]
            previous=(past.get(g["game_id"],{}).get("markets") or {}).get(k,{})
            byname={x["company_display"]:x for x in previous.get("companies",[])}
            delta=[]
            for c in companies:
                old=byname.get(c["company_display"])
                if old:delta.append({"company":c["company_display"],
                    "delta_line":round(c["current"]["line"]-old["current"]["line"],3)})
            markets[k]={"status":m["status"],"company_count":len(companies),
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
    raw="<table>"+''.join(f"<tr><td>机构{i}</td><td>0.90</td><td>220.5</td><td>0.92</td><td>0.88</td><td>{220.5+i}</td><td>0.94</td></tr>" for i in range(12))+"</table>"
    x=extract(raw,"full_total")
    assert len(x)==10 and x[0]["company_display"]=="机构0" and x[-1]["display_rank"]==10
    assert x[0]["company_id"]=="UNVERIFIED"
    o=analyze({"target_date":"2026-10-31","captured_at_utc":"2026-10-30T08:00:00Z","games":[{"game_id":"1234","markets":{"full_total":{"status":"PARSED_VISIBLE_ROWS","companies":x}}}]},None)
    assert o["games"][0]["markets"]["full_total"]["company_count"]==10
    assert not o["model_probability_adjusted"]
    assert len(VALIDATED_SOURCE_IDS)==10 and len(set(VALIDATED_SOURCE_IDS))==10
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
        prior=json.loads(older.read_text()) if older and older.is_file() else {}
        Path(a.out).write_text(json.dumps(snap,ensure_ascii=False,indent=2)+"\n")
        Path(a.analysis).write_text(json.dumps(analyze(snap,prior),ensure_ascii=False,indent=2)+"\n")
        if a.history_root:
            filename=snap["captured_at_utc"].replace(":","-").replace("+","_")+".json"
            (root/filename).write_text(json.dumps(snap,ensure_ascii=False,indent=2)+"\\n")
        print("NBA_TOP10_007",len(snap["games"]))
