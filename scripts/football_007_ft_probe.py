#!/usr/bin/env python3
"""007 score-feed forensic probe; no FT semantics assumed before evidence."""
from collections import Counter
from datetime import datetime,timezone
import argparse,gzip,hashlib,json,re,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import football_007_live_capture as source
import football_007_analysis_extract as analysis

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--match-id',action='append');ap.add_argument('--out-dir',default='football-ft-probe')
 args=ap.parse_args();outdir=Path(args.out_dir);outdir.mkdir(parents=True,exist_ok=True)
 raw=source.fetch(source.FEEDS["fixtures"])
 text=source.text_decode(raw)
 blocks=text.split("$")
 output={"sha256":hashlib.sha256(raw).hexdigest(),"bytes":len(raw),
         "sections":len(blocks),"records":[],"status_counts":{}}
 counts=Counter()
 now=datetime.now(timezone.utc)
 for rec in (blocks[1] if len(blocks)>1 else "").split("!"):
  c=rec.strip().split("^")
  if len(c)<11 or not c[0].isdigit():continue
  counts[c[3]]+=1
  try:tip=source.timestamp(c[1]).astimezone(timezone.utc)
  except (ValueError,IndexError):continue
  if tip<now and len(output["records"])<12:
   output["records"].append({
    "match_id":c[0],"kickoff_utc":tip.isoformat(),"status_at_idx3":c[3],
    "columns_count":len(c),"indexed_fields":{str(i):v[:75] for i,v in enumerate(c[:24])}})
 output["status_counts"]=dict(counts)
 print("FOOTBALL_007_FT_SOURCE_PROBE",json.dumps(output,ensure_ascii=False))
 for mid in (args.match_id or ["2995798","3075305"]):
  try:
   raw=analysis.get_page(mid)
   obj=analysis.decode_json(raw,mid)
   (outdir/(mid+'.html.gz')).write_bytes(gzip.compress(raw,mtime=0))
   html=raw.decode('utf-8-sig')
   header=re.split(r'<script\b',html,flags=re.I)[0]
   body=html[html.lower().find('<body'):]
   clean=re.sub(r'<(script|style)\b[^>]*>.*?</\1>', '',body,flags=re.I|re.S)
   visible=re.sub(r'\s+',' ',re.sub(r'<[^>]+>',' ',clean))
   excerpts=[html[max(0,m.start()-400):m.end()+400] for m in list(re.finditer('完场|90分钟|完賽|已结束|加时|点球',html))[:8]]
   out={"id":mid,"top_keys":list(obj),"scalar_fields":{k:str(v)[:100] for k,v in obj.items() if not isinstance(v,(dict,list))},
        "score_and_status_fields":{k:str(v)[:700] for k,v in obj.items() if any(t in k.lower() for t in ("score","result","state","status","time","goal","home","away")) and isinstance(v,(dict,list))}}
   print("FOOTBALL_007_ANALYSIS_FINAL_SHAPE",json.dumps(out,ensure_ascii=False)[:7000])
   print('FOOTBALL_FT_VISIBLE_HEADER',mid,visible[:2500])
   print('FOOTBALL_FT_HTML_EVIDENCE',mid,json.dumps(excerpts,ensure_ascii=False))
   print('FOOTBALL_FT_INLINE_SCALARS',mid,json.dumps(re.findall(r'\bvar\s+(?!jsonData)\w+\s*=\s*[^;\n]{1,600}',html)[:35],ensure_ascii=False))
  except Exception as exc:print("FOOTBALL_007_ANALYSIS_FINAL_SHAPE_ERROR",mid,type(exc).__name__,str(exc)[:140])
if __name__=="__main__":main()
