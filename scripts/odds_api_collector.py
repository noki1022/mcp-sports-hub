import json,os,urllib.parse,urllib.request

def fetch_odds(sport='basketball_nba',regions='us',markets='spreads,totals,h2h'):
 key=os.environ.get('ODD') or os.environ.get('ODDS_API_KEY')
 if not key: raise RuntimeError('ODDS_API_KEY is not configured')
 q=urllib.parse.urlencode({'apiKey':key,'regions':regions,'markets':markets,'oddsFormat':'decimal'})
 url=f'https://api.the-odds-api.com/v4/sports/{sport}/odds/?{q}'
 req=urllib.request.Request(url,headers={'User-Agent':'nba-cba-analytics/1.0'})
 with urllib.request.urlopen(req,timeout=20) as r: return json.loads(r.read().decode())

def normalize_event(e):
 return {'event_id':e.get('id'),'sport_key':e.get('sport_key'),'start_time':e.get('commence_time'),'home_team':e.get('home_team'),'away_team':e.get('away_team'),'bookmakers':e.get('bookmakers',[]),'source':'The Odds API'}

if __name__=='__main__':
 events=fetch_odds()
 print(json.dumps([normalize_event(e) for e in events],ensure_ascii=False,indent=2))
