#!/usr/bin/env python3
"""Read latest official NBA injury PDF, preserving availability and ambiguity.

NBA publishes PDFs as landscape tables. pdfplumber word coordinates prevent
cross-attributing a player's injury to the next team when plain PDF text reorders
columns. This is not a lineup projection; "not submitted" is not "healthy".
"""
from __future__ import annotations
import argparse,io,json,re,urllib.error,urllib.request,urllib.robotparser
from collections import Counter,defaultdict
from datetime import date,timedelta,datetime,timezone
from html.parser import HTMLParser
from pathlib import Path

INDEX='https://official.nba.com/nba-injury-report-2026-27-season/'
PDF_HOST='https://ak-static.cms.nba.com'
UA='Titan007BasketballResearch/1.0'
STATUS={'Out','Doubtful','Questionable','Probable','Available'}
class Links(HTMLParser):
    def __init__(self):
        super().__init__();self.links=[]
    def handle_starttag(self,tag,attrs):
        if tag=='a':
            href=dict(attrs).get('href','')
            if href.startswith(PDF_HOST+'/referee/injury/Injury-Report_') and href.endswith('.pdf'):
                self.links.append(href)

def checked(url,limit):
    from urllib.parse import urlsplit
    base=urlsplit(url)
    robots=f'{base.scheme}://{base.netloc}/robots.txt'
    try:
        with urllib.request.urlopen(urllib.request.Request(robots,headers={'User-Agent':UA}),timeout=12) as r:
            raw=r.read(120000).decode('utf-8','replace')
        rp=urllib.robotparser.RobotFileParser();rp.parse(raw.splitlines())
        permitted=rp.can_fetch(UA,url)
    except urllib.error.HTTPError as e:
        permitted=e.code in (404,410)
    except Exception:
        permitted=False
    if not permitted:raise RuntimeError('Cannot establish permission to access '+url)
    with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':UA}),timeout=15) as r:
        data=r.read(limit+1)
        if r.status!=200:raise RuntimeError(f'HTTP {r.status}')
    if len(data)>limit:raise RuntimeError('Resource exceeds limited public sample')
    return data

def latest_pdf(et_date:str):
    p=Links()
    p.feed(checked(INDEX,180000).decode('utf-8','replace'))
    needle='Injury-Report_'+et_date+'_'
    valid=[u for u in p.links if needle in u]
    if not valid:raise RuntimeError('No official injury PDF listed for '+et_date)
    # HTML lists them chronologically; never construct undiscovered PDF urls.
    return valid[-1]

def group_words(words):
    a=[]
    for w in sorted(words,key=lambda x:(x['top'],x['x0'])):
        if w['top']<115:continue
        if not a or abs(float(w['top'])-a[-1]['top'])>3.5:
            a.append({'top':float(w['top']),'words':[w]})
        else:
            a[-1]['words'].append(w)
    return a

def is_pdf_pagination_artifact(value):
    """Recognize page-number fragments emitted in the player/team columns."""
    text=re.sub(r'\s+',' ',str(value or '')).strip()
    return bool(re.fullmatch(r'(?:of\s+\d+|page\s+\d+(?:\s+of\s+\d+)?)',text,re.I))


def read_lines(pages):
    current_team=None
    current_matchup=None
    games=defaultdict(lambda:defaultdict(lambda:{'players':[],'report_state':'NO_ROWS_FOUND'}))
    exceptions=[]
    for page in pages:
        for row in group_words(page):
            cols={k:[] for k in ('matchup','team','player','status','reason')}
            for w in row['words']:
                x=float(w['x0']);piece=w['text']
                if 196<=x<260:cols['matchup'].append(piece)
                elif 260<=x<420:cols['team'].append(piece)
                elif 423<=x<580:cols['player'].append(piece)
                elif 580<=x<665:cols['status'].append(piece)
                elif 665<=x:cols['reason'].append(piece)
            m=' '.join(cols['matchup']).strip()
            if re.fullmatch(r'[A-Z]{2,4}@[A-Z]{2,4}',m):
                current_matchup=m
                # Team names must never bleed from previous matchup.
                current_team=None
            team=' '.join(cols['team']).strip()
            if team and team not in ('Team','Date') and not is_pdf_pagination_artifact(team):
                current_team=re.sub(r'\s+',' ',team)
            if not current_matchup or not current_team:continue
            record=games[current_matchup][current_team]
            status=' '.join(cols['status']).strip()
            reason=' '.join(cols['reason']).strip()
            player=' '.join(cols['player']).strip()
            # PDF page footers such as the isolated text 'of 5' can land in
            # the player-name column. They are layout noise, not ambiguous
            # player records, and must not poison the whole team's injury gate.
            if is_pdf_pagination_artifact(player) and not status and not reason:
                continue
            if 'NOT YET SUBMITTED' in reason.upper() or 'NOT YET SUBMITTED' in status.upper():
                record['report_state']='NOT_SUBMITTED'
                continue
            if status in STATUS and player:
                if record['report_state']!='NOT_SUBMITTED':record['report_state']='PUBLISHED'
                record['players'].append({'name':player,'status':status,'reason':reason})
            elif player and not status and not player.startswith('Player'):
                exceptions.append({'matchup':current_matchup,'team':current_team,'raw_player':player})
    result={}
    for m,teams in games.items():
        result[m]={}
        for t,x in teams.items():
            result[m][t]={'report_state':x['report_state'],
                'players':x['players'],
                'status_counts':dict(Counter(p['status'] for p in x['players']))}
    return result,exceptions

def parse_pdf(data):
    if not data.startswith(b'%PDF'):raise ValueError('Not a PDF')
    import pdfplumber
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        pages=[page.extract_words(x_tolerance=2,y_tolerance=2) for page in pdf.pages]
    return read_lines(pages)

def self_test():
    def row(y,segments):
        return [{'text':z,'x0':x,'top':y} for x,z in segments]
    words=(row(129,[(201,'MIA@ATL'),(265,'Miami'),(293,'Heat'),(426,'Fontecchio,'),(482,'Simone'),(587,'Out')])
         +row(151,[(265,'Atlanta'),(300,'Hawks'),(426,'Gueye,'),(455,'Mouhamed'),(587,'Out')])
         +row(173,[(426,'Wiggins,'),(468,'Aaron'),(587,'Questionable')])
         +row(195,[(426,'of'),(440,'5')]))
    games,errors=read_lines([words])
    assert games['MIA@ATL']['Miami Heat']['players'][0]['status']=='Out'
    assert games['MIA@ATL']['Atlanta Hawks']['players'][0]['name']=='Gueye, Mouhamed'
    assert games['MIA@ATL']['Atlanta Hawks']['status_counts']['Questionable']==1
    assert not errors,errors
    assert is_pdf_pagination_artifact('of 5')
    assert is_pdf_pagination_artifact('Page 2 of 5')
    assert not is_pdf_pagination_artifact('Unknown Player')
    malformed=words+row(217,[(426,'UnknownPlayerToken')])
    _,malformed_errors=read_lines([malformed])
    assert len(malformed_errors)==1 and malformed_errors[0]['raw_player']=='UnknownPlayerToken'
    print('OFFICIAL_INJURY_PDF_COORD_AND_PAGINATION_NOISE_TEST_PASS')

def run(target_date,out,min_matchups=10):
    # NBA morning games shown in China on target_date were previous US ET day.
    et=(date.fromisoformat(target_date)-timedelta(days=1)).isoformat()
    url=latest_pdf(et)
    games,errors=parse_pdf(checked(url,1500000))
    if len(games)<min_matchups:raise RuntimeError(f'Official PDF parse incomplete: {len(games)} matchups (required {min_matchups})')
    report={
        'captured_at_utc':datetime.now(timezone.utc).isoformat(),
        'report_et_date':et,
        'source_url':url,
        'official_source_index':INDEX,
        'matchup_count':len(games),
        'matchups':games,
        'ambiguous_player_rows':errors[:40],
        'warning':'Official injury report is a changing pregame snapshot; any missing team, NOT_SUBMITTED, questionable starter or old timestamp blocks confirmed value picks.'
    }
    Path(out).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'pdf':url,'matchup_count':len(games),'ambiguous_count':len(errors),'samples':{m:games[m] for m in ('MIA@ATL','CHA@DET') if m in games}},ensure_ascii=False,indent=2)[:9500])
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--self-test',action='store_true')
    p.add_argument('--date',default='2026-10-29')
    p.add_argument('--out',default='nba_official_injuries.json')
    p.add_argument('--min-matchups',type=int,default=10)
    a=p.parse_args()
    if a.self_test:self_test()
    else:
        if not 1 <= a.min_matchups <= 30:raise SystemExit('INVALID_MIN_MATCHUPS')
        run(a.date,a.out,a.min_matchups)
