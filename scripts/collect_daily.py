import os,sys
sys.path.insert(0,'scripts')
def main():
 key=os.getenv('ODD') or os.getenv('ODDS_API_KEY'); print('ODD configured:',bool(key))
 if not key: print('Odds collector skipped: missing ODD'); return 0
 try:
  from odds_api_collector import fetch_odds,normalize_event
  events=[normalize_event(e) for e in fetch_odds('basketball_nba')]
  books=sorted({b.get('title') or b.get('key') for e in events for b in e.get('bookmakers',[])})
  print('NBA odds events:',len(events)); print('bookmakers:',len(books)); print('source: The Odds API (not Crown)'); return 0
 except Exception:
  print('Odds collector failed: sanitized error; inspect API status without exposing credentials'); return 1
if __name__=='__main__': raise SystemExit(main())
