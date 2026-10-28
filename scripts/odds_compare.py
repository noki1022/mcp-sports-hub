from typing import Any

def compare_snapshots(old:dict,new:dict)->list[dict[str,Any]]:
    def key(m): return (m.get('book'),m.get('market'),m.get('format'),m.get('phase'),m.get('home_line'),m.get('away_line'),m.get('total_line'))
    oldm={key(m):m for m in old.get('markets',[])}; out=[]
    for nm in new.get('markets',[]):
        om=oldm.get(key(nm))
        if not om: continue
        changes={}
        for f in ('home_price','away_price','over_price','under_price','home_line','away_line','total_line'):
            if om.get(f)!=nm.get(f): changes[f]={'old':om.get(f),'new':nm.get(f)}
        if changes: out.append({'book':nm.get('book'),'market':nm.get('market'),'format':nm.get('format'),'changes':changes})
    return out
