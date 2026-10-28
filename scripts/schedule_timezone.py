from datetime import datetime,timezone
from zoneinfo import ZoneInfo
from .base import Game
CN=ZoneInfo('Asia/Shanghai')
def beijing_date(utc_iso:str)->str:
 s=utc_iso.replace('Z','+00:00'); dt=datetime.fromisoformat(s)
 if dt.tzinfo is None: dt=dt.replace(tzinfo=timezone.utc)
 return dt.astimezone(CN).date().isoformat()
def beijing_time(utc_iso:str)->str:
 s=utc_iso.replace('Z','+00:00'); dt=datetime.fromisoformat(s)
 if dt.tzinfo is None: dt=dt.replace(tzinfo=timezone.utc)
 return dt.astimezone(CN).isoformat(timespec='minutes')
def filter_day(games:list[Game],date_cn:str)->list[dict]:
 out=[]
 for g in games:
  if not g.start_time_utc or beijing_date(g.start_time_utc)!=date_cn: continue
  out.append({'game_id':g.game_id,'league':g.league,'start_time_beijing':beijing_time(g.start_time_utc),'home_team':g.home_team,'away_team':g.away_team,'status':g.status,'source':g.source})
 return out
