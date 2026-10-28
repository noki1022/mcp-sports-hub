import json,os,sys
from datetime import datetime,timezone
sys.path.insert(0,'scripts')
def main():
 key=(os.getenv('THE_ODDS_API_KEY') or os.getenv('ODDS_API_KEY')
      or os.getenv('ODD')); print('ODD configured:',bool(key))
 if not key: print('Odds collector skipped: missing ODD'); return 0
 try:
  from odds_api_collector import fetch_odds,normalize_event
  events=[normalize_event(e) for e in fetch_odds('basketball_nba')]
  books=sorted({b.get('title') or b.get('key') for e in events for b in e.get('bookmakers',[])})
  captured=datetime.now(timezone.utc); os.makedirs('data/odds',exist_ok=True)
  path=f"data/odds/{captured:%Y-%m-%d_%H%M%S}_the_odds_api.json"
  with open(path,'w',encoding='utf-8') as f: json.dump({'captured_at':captured.isoformat(),'source':'The Odds API','sport':'basketball_nba','events':events},f,ensure_ascii=False,indent=2)
  print('NBA odds events:',len(events)); print('bookmakers:',len(books)); print('saved:',path); print('source: The Odds API (not Crown)'); return 0
 except Exception:
  print('Odds collector failed: sanitized error'); return 1
if __name__=='__main__': raise SystemExit(main())
