#!/usr/bin/env python3
"""007 score-feed forensic probe; no FT semantics assumed before evidence."""
from collections import Counter
from datetime import datetime,timezone
import hashlib,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import football_007_live_capture as source

def main():
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
if __name__=="__main__":main()
