import json,sqlite3
from pathlib import Path
class Store:
 def __init__(self,path='data/history.sqlite3'):
  Path(path).parent.mkdir(parents=True,exist_ok=True); self.db=sqlite3.connect(path)
  self.db.execute('create table if not exists snapshots (snapshot_id text primary key, game_id text, league text, captured_at text, payload text)'); self.db.commit()
 def put(self,d):
  self.db.execute('insert or replace into snapshots values (?,?,?,?,?)',(d['snapshot_id'],d['game_id'],d.get('league'),d['captured_at'],json.dumps(d,ensure_ascii=False))); self.db.commit()
 def get(self,snapshot_id):
  r=self.db.execute('select payload from snapshots where snapshot_id=?',(snapshot_id,)).fetchone(); return json.loads(r[0]) if r else None
