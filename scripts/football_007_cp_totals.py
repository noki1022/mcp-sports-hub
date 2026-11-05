#!/usr/bin/env python3
"""Read-only CP titan007 Jingcai EXACT TOTAL GOALS (0..7+) odds parser.

Verified on 2026-11-05 public cp.titan007.com/buy/jingcai.aspx
?typeID=103&oddstype=2. A CP betting row id (e.g. 5575002) is NOT the
007 fixture id (e.g. 3075305). Fixture id comes from HomeTeam_<id> and
GuestTeam_<id> anchor attributes. No name-only matches are permitted.
"""
from __future__ import annotations

from datetime import datetime
from html.parser import HTMLParser
import re
import urllib.request
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

CP_TTG_URL="https://cp.titan007.com/buy/jingcai.aspx?typeID=103&oddstype=2"
BJ=ZoneInfo("Asia/Shanghai")
LABELS=tuple([str(i)+"球" for i in range(7)]+["7+球"])
CAP=850000

class Rows(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows=[];self.row=None;self.cell=None;self.forms=[]
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=="form":self.forms.append(a)
        if tag=="tr" and re.fullmatch(r"row_\d{5,12}",a.get("id","")):
            if self.row is not None:raise ValueError("NESTED_TTG_MATCH_ROWS")
            self.row={"attrs":a,"cells":[]}
        if tag in ("td","th") and self.row is not None:
            if self.cell is not None:raise ValueError("NESTED_TTG_CELL")
            self.cell={"attrs":a,"text":[],"anchors":[]}
        if tag=="a" and self.cell is not None:
            self.cell["anchors"].append(a)
    def handle_data(self,v):
        if self.cell is not None:self.cell["text"].append(v)
    def handle_endtag(self,tag):
        if tag in ("td","th") and self.cell is not None:
            self.cell["text"]=" ".join(" ".join(self.cell["text"]).split())
            self.row["cells"].append(self.cell);self.cell=None
        if tag=="tr" and self.row is not None:
            if self.cell is not None:raise ValueError("UNCLOSED_TTG_CELL")
            self.rows.append(self.row);self.row=None

def fetch_cp_ttg():
    req=urllib.request.Request(CP_TTG_URL,headers={
        "User-Agent":"Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0",
        "Accept":"text/html,application/xhtml+xml,*/*;q=0.8",
        "Accept-Language":"zh-CN,zh;q=0.9",
        "Referer":"https://cp.titan007.com/"})
    with urllib.request.urlopen(req,timeout=18) as res:
        if res.status!=200 or res.url!=CP_TTG_URL:
            raise ValueError("CP_TTG_HTTP_STATUS_OR_REDIRECT")
        if urlparse(res.url).hostname!="cp.titan007.com":
            raise ValueError("INVALID_CP_TTG_HOST")
        raw=res.read(CAP+1)
        if not raw or len(raw)>CAP:
            raise ValueError("CP_TTG_EMPTY_OR_EXCESS")
        return raw

def decode(raw):
    if not isinstance(raw,bytes) or len(raw)>CAP:raise ValueError("INVALID_CP_TTG_HTML_BYTES")
    return raw.decode("utf-8-sig")

def fixture_id(cell,tag):
    ids=[]
    for a in cell["anchors"]:
        value=a.get("id","")
        m=re.fullmatch(re.escape(tag)+r"_(\d{4,10})",value)
        if m:ids.append(m.group(1))
    return ids[0] if len(ids)==1 else None

def odds_tuple(cells,bet_id):
    odds=[]
    for i,cell in enumerate(cells[9:17]):
        if cell["attrs"].get("title")!=LABELS[i]:
            raise ValueError("TTG_CELL_ORDER_MISMATCH")
        if cell["attrs"].get("id")!=f"cell_{bet_id}_{i+1}":
            raise ValueError("TTG_CELL_BET_ID_MISMATCH")
        value=cell["text"].strip()
        if not value:
            return None
        try:num=float(value)
        except ValueError:return None
        if not 1.001<=num<=1000.0:return None
        odds.append(num)
    return odds if len(odds)==8 else None

def parse_cp_ttg(raw):
    page=decode(raw)
    parsed=Rows();parsed.feed(page)
    if not any("typeid=103" in str(x.get("action","")).lower()
               for x in parsed.forms):
        raise ValueError("CP_PAGE_NOT_TTG_TYPE_103")
    result={}
    statuses={"rows_seen":0,"eight_quotes":0,"missing_quote":0,
              "invalid_rows":0,"betting_rows":0}
    seen_betids=set()
    for row in parsed.rows:
        attr=row["attrs"]
        m=re.fullmatch(r"row_(\d{5,12})",attr.get("id",""))
        if not m:continue
        statuses["rows_seen"]+=1
        bet_id=m.group(1)
        if bet_id in seen_betids:raise ValueError("DUPLICATE_CP_BETTING_ROW")
        seen_betids.add(bet_id)
        cells=row["cells"]
        if len(cells)<17 or not re.fullmatch(r"\d{3}",cells[0]["text"]):
            statuses["invalid_rows"]+=1
            continue
        match_id=fixture_id(cells[4],"HomeTeam")
        away_id=fixture_id(cells[6],"GuestTeam")
        if match_id is None or match_id!=away_id:
            statuses["invalid_rows"]+=1
            continue
        if match_id in result:raise ValueError("DUPLICATE_CP_007_FIXTURE_ID")
        prefix=attr.get("name","").strip()
        if prefix not in ("周一","周二","周三","周四","周五","周六","周日","周天"):
            statuses["invalid_rows"]+=1
            continue
        kickoff_str=cells[2]["attrs"].get("title","").replace("开赛时间：","").strip()
        try:kickoff=datetime.strptime(kickoff_str,"%Y-%m-%d %H:%M").replace(tzinfo=BJ)
        except ValueError:
            statuses["invalid_rows"]+=1
            continue
        quotes=odds_tuple(cells,bet_id)
        statuses["betting_rows"]+=1
        statuses["eight_quotes" if quotes is not None else "missing_quote"]+=1
        result[match_id]={
            "match_id":match_id,
            "jc_number":prefix+cells[0]["text"],
            "cp_bet_id":bet_id,
            "home_team_cp":cells[4]["text"],
            "away_team_cp":cells[6]["text"],
            "kickoff_beijing":kickoff.isoformat(),
            "can_sale":attr.get("cansale")=="true",
            "odds":quotes
        }
    if not result or statuses["rows_seen"]==0:
        raise ValueError("CP_TTG_NO_RECOGNIZED_MATCH_ROWS")
    return result,statuses

def join_fixture(game,by_match_id):
    """Match ONLY by 007 fixture id + JC number + kickoff. No fuzzy name matching."""
    found=by_match_id.get(str(game["match_id"]))
    if not found:return None,"CP_TTG_FIXTURE_ID_MISSING"
    if found["jc_number"]!=game["jc_number"]:
        return None,"CP_TTG_JC_NUMBER_MISMATCH"
    if datetime.fromisoformat(found["kickoff_beijing"])!=datetime.fromisoformat(game["kickoff_beijing"]):
        return None,"CP_TTG_KICKOFF_MISMATCH"
    if not found["odds"]:return None,"CP_TTG_QUOTE_MISSING"
    return found["odds"],"VERIFIED_MATCH_ID_JC_NUMBER_KICKOFF"
