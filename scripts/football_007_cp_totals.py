#!/usr/bin/env python3
"""Read-only CP titan007 Jingcai EXACT TOTAL GOALS (0..7+) odds parser.

Verified on 2026-11-05 public cp.titan007.com/buy/jingcai.aspx
?typeID=103&oddstype=2. A CP betting row id (e.g. 5575002) is NOT the
007 fixture id (e.g. 3075305). Fixture id comes from HomeTeam_<id> and
GuestTeam_<id> anchor attributes. No name-only matches are permitted.
"""
from __future__ import annotations

from datetime import date, datetime
from html.parser import HTMLParser
import re
import urllib.request
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

CP_TTG_URL="https://cp.titan007.com/buy/jingcai.aspx?typeID=103&oddstype=2"
CP_HAD_URL="https://cp.titan007.com/buy/jingcai.aspx?typeID=101&oddstype=2"
BJ=ZoneInfo("Asia/Shanghai")
LABELS=tuple([str(i)+"球" for i in range(7)]+["7+球"])
CAP=850000

class Rows(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows=[];self.row_stack=[];self.cell_stack=[];self.forms=[]
        self.sale_day=None
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=="form":self.forms.append(a)
        if tag=="tr":
            self.row_stack.append({"attrs":a,"cells":[],"subrows":[],"sale_day":self.sale_day})
        if tag in ("td","th") and self.row_stack:
            self.cell_stack.append({"attrs":a,"text":[],"anchors":[],"elements":[]})
        if self.cell_stack:
            self.cell_stack[-1]["elements"].append((tag,a))
            if tag=="a":self.cell_stack[-1]["anchors"].append(a)
    def handle_data(self,v):
        if self.cell_stack:self.cell_stack[-1]["text"].append(v)
    def handle_endtag(self,tag):
        if tag in ("td","th") and self.cell_stack and self.row_stack:
            cell=self.cell_stack.pop()
            cell["text"]=" ".join(" ".join(cell["text"]).split())
            self.row_stack[-1]["cells"].append(cell)
        if tag=="tr" and self.row_stack:
            row=self.row_stack.pop()
            if self.row_stack:
                self.row_stack[-1]["subrows"].append(row)
            else:
                text=" ".join(c["text"] for c in row["cells"])
                m=re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日\s+星期",text)
                if m:self.sale_day=date(*map(int,m.groups())).isoformat()
                if re.fullmatch(r"row_\d{5,12}",row["attrs"].get("id","")):
                    self.rows.append(row)

def fetch_cp_page(url=CP_TTG_URL):
    req=urllib.request.Request(url,headers={
        "User-Agent":"Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0",
        "Accept":"text/html,application/xhtml+xml,*/*;q=0.8",
        "Accept-Language":"zh-CN,zh;q=0.9",
        "Referer":"https://cp.titan007.com/"})
    with urllib.request.urlopen(req,timeout=18) as res:
        if res.status!=200 or res.url!=url:
            raise ValueError("CP_TTG_HTTP_STATUS_OR_REDIRECT")
        if urlparse(res.url).hostname!="cp.titan007.com":
            raise ValueError("INVALID_CP_TTG_HOST")
        raw=res.read(CAP+1)
        if not raw or len(raw)>CAP:
            raise ValueError("CP_TTG_EMPTY_OR_EXCESS")
        return raw

def fetch_cp_ttg():
    return fetch_cp_page()

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
            "sale_day_beijing":row["sale_day"],
            "league":cells[1]["text"],
            "league_id_007":next((int(m.group(1)) for a in cells[1]["anchors"]
                if (m:=re.search(r"/(\d+)\.html",a.get("href","")))),None),
            "home_team_id_007":next((int(m.group(1)) for tag,a in cells[4]["elements"]
                if (m:=re.fullmatch(r"Vs_"+match_id+r"_(\d+)",a.get("id","")))),None),
            "away_team_id_007":next((int(m.group(1)) for tag,a in cells[6]["elements"]
                if (m:=re.fullmatch(r"Vs_"+match_id+r"_(\d+)",a.get("id","")))),None),
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

def parse_cp_had(raw):
    parsed=Rows();parsed.feed(decode(raw))
    if not any("typeid=101" in a.get("action","").lower() for a in parsed.forms):
        raise ValueError("CP_PAGE_NOT_HAD_TYPE_101")
    result={}
    for row in parsed.rows:
        cells=row["cells"]
        home=next((c for c in cells if fixture_id(c,"HomeTeam")),None)
        away=next((c for c in cells if fixture_id(c,"GuestTeam")),None)
        if not home or not away:raise ValueError("CP_HAD_TEAM_ID_MISSING")
        mid=fixture_id(home,"HomeTeam")
        if mid!=fixture_id(away,"GuestTeam") or mid in result:
            raise ValueError("CP_HAD_IDENTITY_CONFLICT")
        bet=row["attrs"]["id"].removeprefix("row_")
        prefix=row["attrs"].get("name","")
        label=prefix+cells[0]["text"]
        if not re.fullmatch(r"周[一二三四五六日天]\d{3}",label):
            raise ValueError("CP_HAD_NUMBER_INVALID")
        clock=next((c["attrs"]["title"].removeprefix("开赛时间：") for c in cells
                    if c["attrs"].get("title","").startswith("开赛时间：")),None)
        tip=datetime.strptime(clock or "","%Y-%m-%d %H:%M").replace(tzinfo=BJ)
        pools={sub["attrs"].get("id"):sub["cells"] for sub in row["subrows"]}
        def prices(sub_id,ids):
            pool=pools.get(sub_id,[])
            values=[]
            for i,title in zip(ids,("主胜","平局","客胜")):
                cell=next((c for c in pool if c["attrs"].get("id")==f"cell_{bet}_{i}"),None)
                if cell is None:return None
                if cell["attrs"].get("title")!=title:raise ValueError("CP_HAD_PRICE_ORDER")
                try:value=float(cell["text"])
                except ValueError:return None
                if not 1<value<=1000:return None
                values.append(value)
            return values
        had=prices("spfTr_"+bet,(52,53,54))
        hhad=prices("rqTr_"+bet,(1,2,3))
        handicap=row["attrs"].get("polygoal","")
        if hhad is not None and not re.fullmatch(r"[+-]?\d+",handicap):
            raise ValueError("CP_HHAD_HANDICAP_INVALID")
        result[mid]={"jc_number":label,"kickoff_beijing":tip.isoformat(),
            "home_team_cp":home["text"],"away_team_cp":away["text"],
            "had":had,"hhad":({"signed_home_handicap":int(handicap),"odds":hhad} if hhad else None),
            "had_not_on_sale":any("未开售胜平负" in c["text"] for c in pools.get("spfTr_"+bet,[]))}
    if not result:raise ValueError("CP_HAD_NO_RECOGNIZED_MATCH_ROWS")
    return result
