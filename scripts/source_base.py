from dataclasses import dataclass
from typing import Any, Protocol
@dataclass
class Game:
    game_id:str; league:str; start_time_utc:str; home_team:str; away_team:str; status:str='scheduled'; source:str='unknown'
class ScheduleSource(Protocol):
    def fetch(self, date_beijing:str)->list[dict[str,Any]]: ...
def normalize_game(raw:dict,league:str,source:str)->Game:
    return Game(game_id=str(raw.get('game_id') or raw.get('id') or 'UNKNOWN'),league=league,start_time_utc=raw.get('kickoff') or raw.get('start_time_utc') or '',home_team=raw.get('home_team') or raw.get('home') or 'UNKNOWN',away_team=raw.get('away_team') or raw.get('away') or 'UNKNOWN',status=raw.get('status','scheduled'),source=source)
