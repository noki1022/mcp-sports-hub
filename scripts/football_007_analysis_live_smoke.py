#!/usr/bin/env python3
"""Single real 007 future-match parser smoke test; keeps raw evidence."""
import sys,json,gzip,hashlib
from datetime import datetime,timezone
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import football_007_analysis_extract as analysis
import football_007_live_capture as capture

def main():
 ts=datetime.now(timezone.utc)
 f=capture.fetch(capture.FEEDS["fixtures"])
 odds=capture.fetch(capture.FEEDS["jc_odds"])
 data=capture.collect({"fixtures":f,"jc_odds":odds},ts)
 choices=data["games"]
 # Inspect the first available future 007 match, not a hard-coded past match.
 out_dir=Path("football-output/analysis-smoke")
 out_dir.mkdir(parents=True,exist_ok=True)
 first_errors=[]
 for game in choices[:5]:
  try:
   raw=analysis.get_page(game["match_id"])
   path=out_dir/(game["match_id"]+".html.gz")
   path.write_bytes(gzip.compress(raw,mtime=0))
   result=analysis.extract(raw,game,datetime.now(timezone.utc).isoformat())
   summary={"match_id":game["match_id"],"jc_number":game["jc_number"],
            "home_recent":len(result["home_last5"]),
            "away_recent":len(result["away_last5"]),"h2h":len(result["h2h"]),
            "injury_facts":len(result["injury_source_facts"]),
            "injury_state":result["injury_report_state"],
            "sha256":hashlib.sha256(raw).hexdigest(),
            "source":result["source_evidence"]}
   (out_dir/"sample.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n")
   print("007_ANALYSIS_REAL_EXTRACTION",json.dumps(summary,ensure_ascii=False))
   return
  except Exception as exc:
   first_errors.append({"match_id":game["match_id"],"error":type(exc).__name__+":"+str(exc)[:120]})
 print("007_ANALYSIS_NO_EXTRACTABLE_SAMPLE",json.dumps(first_errors,ensure_ascii=False))
 raise SystemExit("NO_007_ANALYSIS_SAMPLES_PARSED")
if __name__=="__main__":main()
