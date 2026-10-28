import sys;sys.path.insert(0,'src')
from sources.base import Game
from sources.schedule import filter_day
x=Game('x','NBA','2026-10-28T23:00:00Z','IND','PHI',source='test')
assert filter_day([x],'2026-10-29')[0]['start_time_beijing'].startswith('2026-10-29T07:00')
assert filter_day([x],'2026-10-28')==[]
print('schedule ok')
