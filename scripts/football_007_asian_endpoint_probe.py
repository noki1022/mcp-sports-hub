#!/usr/bin/env python3
"""Inspect the verified 007 mobile Asian odds endpoint and its JSON schema.

Bounded read-only probe. Endpoint path and query construction are taken from
the actual m.titan007.com/script/letgoalOverunderData.js LoadData().
No invented company prices or assumptions about unknown field meanings.
"""
import hashlib, json, re, urllib.request, urllib.parse
from datetime import datetime,timezone

MID="3075305"
PAGE=f"https://m.titan007.com/asian/{MID}.htm"
JS="https://m.titan007.com/script/letgoalOverunderData.js"
ROOT="https://m.titan007.com/"
def fetch(url,size=800000):
 req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0","Accept-Language":"zh-CN,zh;q=0.9","Referer":PAGE})
 with urllib.request.urlopen(req,timeout=17) as r:
  if r.status!=200 or urllib.parse.urlsplit(r.url).hostname!="m.titan007.com":raise RuntimeError("SOURCE_HOST_OR_STATUS_ERROR")
  raw=r.read(size+1)
  if not raw or len(raw)>size:raise RuntimeError("SOURCE_TOO_LARGE_OR_EMPTY")
  return raw
def snippet(s,k,before=150,after=650):
 at=s.lower().find(k.lower())
 return None if at<0 else re.sub(r"\s+"," ",s[max(0,at-before):at+after])
p=fetch(PAGE)
page=p.decode("utf-8-sig","replace")
js=fetch(JS,size=350000).decode("utf-8-sig","replace")
for key in ("oddskind","isHalf","scheduleId","letgoalOverunderData","HandicapDataInterface","LoadData","function make","var company","initial","firstHomeOdds"):
 print("ASIAN_PAGE_SCRIPT",json.dumps({"term":key,"page":snippet(page,key),"js":snippet(js,key)},ensure_ascii=False))
print("ASIAN_SOURCE_HASHES",json.dumps({"page_sha256":hashlib.sha256(p).hexdigest(),"script_sha256":hashlib.sha256(js.encode()).hexdigest()},ensure_ascii=False))
# Read only the endpoint directly referenced by the source JS.
# This page sets scheduleId, oddskind and isHalf; do not guess user params.
param={}
for name in ("scheduleId","oddskind","isHalf"):
 matches=re.findall(r"(?:(?:var|let|const)\s+)?"+name+r"\s*=\s*([0-9]+)\s*[;,]",page)
 print("ASIAN_PAGE_PARAMS",name,json.dumps(matches))
 if len(set(matches))==1:param[name]=matches[0]
if "scheduleId" not in param or param["scheduleId"]!=MID:
 # ScheduleId may be emitted via a separate page variable statement.
 print("ASIAN_DATA_SKIP_UNVERIFIED_PAGE_MATCH_ID",json.dumps(param))
 raise SystemExit(0)
# Defaults are only permitted when visible as constants in actual JS.
for name in ("oddskind","isHalf"):
 if name not in param:
  found=re.findall(r"(?:(?:var|let|const)\s+)?"+name+r"\s*=\s*([0-9]+)\s*[;,]",js)
  if len(set(found))==1:param[name]=found[0]
if "oddskind" not in param or "isHalf" not in param:
 print("ASIAN_DATA_SKIP_UNVERIFIED_SOURCE_PARAMS",json.dumps(param))
 raise SystemExit(0)
endpoint=ROOT+"HandicapDataInterface.ashx?"+urllib.parse.urlencode({"scheid":MID,"type":"1","oddskind":param["oddskind"],"isHalf":param["isHalf"]})
try:raw=fetch(endpoint,900000)
except Exception as exc:
 print("ASIAN_ENDPOINT_REQUEST_FAILED",type(exc).__name__,str(exc)[:160]);raise SystemExit(0)
txt=raw.decode("utf-8-sig","replace")
print("ASIAN_ENDPOINT_HTTP",json.dumps({"url":endpoint,"bytes":len(raw),"sha256":hashlib.sha256(raw).hexdigest(),"prefix":txt[:500]},ensure_ascii=False))
try:obj=json.loads(txt)
except (ValueError,TypeError) as exc:
 print("ASIAN_ENDPOINT_JSON_INVALID",type(exc).__name__);raise SystemExit(0)
if not isinstance(obj,dict):
 print("ASIAN_ENDPOINT_WRONG_SHAPE",type(obj).__name__);raise SystemExit(0)
report={"keys":list(obj),"company_count":len(obj.get("companies") or []),"status":obj.get("status")}
for c in (obj.get("companies") or [])[:5]:
 if not isinstance(c,dict):continue
 report.setdefault("sample_companies",[]).append({
  "company_keys":list(c),
  "company_id":c.get("companyId"),
  "company_name":c.get("companyName"),
  "detail_count":len(c.get("details") or []),
  "detail_keys":list((c.get("details") or [{}])[0]),
  "first_detail":(c.get("details") or [None])[0]
 })
print("ASIAN_ENDPOINT_JSON_SHAPE",json.dumps(report,ensure_ascii=False))
