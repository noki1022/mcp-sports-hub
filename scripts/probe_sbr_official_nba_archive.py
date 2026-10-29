#!/usr/bin/env python3
"""Inspect the actual Sportsbook Reviews Online NBA archive, without ingestion.

Network requests are bounded and read-only; no downloaded content is saved.
The status of a URL is NOT evidence of data; we verify actual columns/rows.
Saved third-party HTML is classified as a mirror and not blindly promoted.
"""
from __future__ import annotations
import hashlib
from html.parser import HTMLParser
import json
import re
from urllib.error import HTTPError,URLError
from urllib.request import Request,urlopen

BASE="https://www.sportsbookreviewsonline.com"
INDEX=BASE+"/scoresoddsarchives/nba/nbaoddsarchives.htm"
PATHS=[
    "/scoresoddsarchives/nba/nbaoddsarchives.htm",
    "/scoresoddsarchives/nba-odds-2007-08/",
    "/scoresoddsarchives/nba-odds-2019-20/",
    "/scoresoddsarchives/nba-odds-2022-23/",
    "/scoresoddsarchives/nba-odds-2023-24/",
]
REQUIRED={"Date","Rot","VH","Team","Final","Open","Close","ML"}
MIRROR_2022="https://raw.githubusercontent.com/Swiptype/Modele_predictif_paris_M1/master/nba_odds.html"

class Tables(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tr=None;self.cell=None;self.rows=[];self.links=[];self.title=""
        self.intitle=False
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if tag=="tr":self.tr=[]
        if tag in ("td","th") and self.tr is not None:self.cell=[]
        if tag=="a" and "href" in attrs:self.links.append(attrs["href"])
        if tag=="title":self.intitle=True
    def handle_data(self,data):
        if self.cell is not None:self.cell.append(data)
        if self.intitle:self.title+=data
    def handle_endtag(self,tag):
        if tag in ("td","th") and self.tr is not None and self.cell is not None:
            self.tr.append(" ".join("".join(self.cell).split()));self.cell=None
        if tag=="tr" and self.tr is not None:
            if self.tr:self.rows.append(self.tr)
            self.tr=None
        if tag=="title":self.intitle=False

def download(url,max_bytes=1_200_000):
    req=Request(url,headers={"User-Agent":"mcp-sports-hub-research-integrity-audit/1.0","Accept":"text/html"})
    with urlopen(req,timeout=22) as response:
        data=response.read(max_bytes+1)
        if len(data)>max_bytes: raise ValueError("TOO_LARGE_FOR_BOUNDED_PROBE")
        return response.status,response.url,data,response.headers.get("Content-Type","")

def inspect(label,url):
    try:
        status,final,data,ctype=download(url)
        text=data.decode("utf-8-sig","replace")
        parser=Tables();parser.feed(text)
        heads=[i for i,r in enumerate(parser.rows) if REQUIRED.issubset(r)]
        data_rows=0
        if heads:
            h=heads[0]
            data_rows=sum(len(r)>=8 and len(r)>2 and r[2] in ("H","V") for r in parser.rows[h+1:])
        linked=sorted(set(re.findall(r"/scoresoddsarchives/nba-odds-\d{4}-\d\d",text)))
        return {"label":label,"http":status,"url":url,"final_url":final,"bytes":len(data),
                "sha256":hashlib.sha256(data).hexdigest(),"content_type":ctype[:70],
                "title":parser.title[:130],"table_rows":len(parser.rows),
                "sbr_header_found":bool(heads),"team_rows":data_rows,
                "season_links_count":len(linked),
                "season_links":linked if label=="index" else [],
                "valid_nba_archive":bool(heads and data_rows>500),
                "source_status":"RESEARCH_ONLY_NO_TRAINING_APPROVAL"}
    except (HTTPError,URLError,ValueError,TimeoutError,OSError) as exc:
        return {"label":label,"url":url,"error":type(exc).__name__+":"+str(exc)[:170],
                "valid_nba_archive":False,"source_status":"UNREACHABLE_OR_INVALID"}

def main():
    for path in PATHS:
        label="index" if path.endswith(".htm") else path.strip("/").split("/")[-1]
        res=inspect(label,BASE+path)
        print("SBR_DIRECT_ARCHIVE_PROBE "+json.dumps(res,ensure_ascii=False,sort_keys=True),flush=True)
    # A public copy is NOT a replacement for an authorized official source.
    result=inspect("unlicensed_public_2022_23_html_mirror",MIRROR_2022)
    print("SBR_ARCHIVE_MIRROR_PROBE "+json.dumps(result,ensure_ascii=False,sort_keys=True),flush=True)
    print("SBR_ARCHIVE_ADMISSION "+json.dumps({"training_admitted":0,
        "direct_website_fetch_is_not_license_proof":True,
        "opening_and_closing_are_labels_without_quote_timestamps":True,
        "no_raw_archive_saved":True},sort_keys=True))
if __name__=="__main__": main()
