from .base import normalize_game
class ManualOrApiSource:
    """Adapter shell. Network/auth is injected by caller; no credentials in repo."""
    def __init__(self,league,source): self.league,self.source=league,source
    def parse(self,payload): return [normalize_game(x,self.league,self.source) for x in payload.get('games',[])]

def nba_from_statshawk(payload): return ManualOrApiSource('NBA','StatsHawk').parse(payload)
def nba_from_nba_api(payload): return ManualOrApiSource('NBA','nba_api').parse(payload)
def cba_from_apizero(payload): return ManualOrApiSource('CBA','ApiZero').parse(payload)
def cba_from_official(payload): return ManualOrApiSource('CBA','CBA official').parse(payload)
