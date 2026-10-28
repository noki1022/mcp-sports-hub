#!/usr/bin/env python3
"""Experimental NBA spread/total EV analysis from real 007 Crow* + NBA form/boxscore + official injury PDF.

Fail-closed: inputs without provenance are not invented, uncalibrated probabilities
cannot produce "BET" recommendations, and official injury names are not
assigned speculative point adjustments.
"""
from __future__ import annotations
import argparse,csv,html,json,math
from datetime import datetime,timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import titan007_market_math as mathodds

NAMES={
 "亚特兰大老鹰":("ATL","Atlanta Hawks"),
 "迈阿密热火":("MIA","Miami Heat"),
 "克里夫兰骑士":("CLE","Cleveland Cavaliers"),
 "华盛顿奇才":("WAS","Washington Wizards"),
 "底特律活塞":("DET","Detroit Pistons"),
 "夏洛特黄蜂":("CHA","Charlotte Hornets"),
 "印第安纳步行者":("IND","Indiana Pacers"),
 "费城76人":("PHI","Philadelphia 76ers"),
 "多伦多猛龙":("TOR","Toronto Raptors"),
 "奥兰多魔术":("ORL","Orlando Magic"),
 "明尼苏达森林狼":("MIN","Minnesota Timberwolves"),
 "金州勇士":("GSW","Golden State Warriors"),
 "新奥尔良鹈鹕":("NOP","New Orleans Pelicans"),
 "丹佛掘金":("DEN","Denver Nuggets"),
 "芝加哥公牛":("CHI","Chicago Bulls"),
 "纽约尼克斯":("NYK","New York Knicks"),
 "密尔沃基雄鹿":("MIL","Milwaukee Bucks"),
 "休斯顿火箭":("HOU","Houston Rockets"),
 "犹他爵士":("UTA","Utah Jazz"),
 "圣安东尼奥马刺":("SAS","San Antonio Spurs"),
 "达拉斯独行侠":("DAL","Dallas Mavericks"),
 "俄克拉荷马城雷霆":("OKC","Oklahoma City Thunder"),
 "洛杉矶快船":("LAC","LA Clippers"),
 "洛杉矶湖人":("LAL","Los Angeles Lakers"),
 "波士顿凯尔特人":("BOS","Boston Celtics"),
 "布鲁克林篮网":("BKN","Brooklyn Nets"),
 "孟菲斯灰熊":("MEM","Memphis Grizzlies"),
 "波特兰开拓者":("POR","Portland Trail Blazers"),
 "菲尼克斯太阳":("PHX","Phoenix Suns"),
 "萨克拉门托国王":("SAC","Sacramento Kings"),
}

def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))

def quality(game,bench):
    if game.get('league')!='NBA':return ['NOT_NBA']
    issues=[]
    if bench['efficiency_games_home']<8 or bench['efficiency_games_away']<8:issues.append('EARLY_SEASON_LOW_SAMPLE')
    if bench['standings_games_home']<8 or bench['standings_games_away']<8:issues.append('SEASON_TOO_FEW_GAMES')
    if bench['injury_home'].get('report_state')!='PUBLISHED':issues.append('INJURY_REPORT_HOME_MISSING_OR_UNSUBMITTED')
    if bench['injury_away'].get('report_state')!='PUBLISHED':issues.append('INJURY_REPORT_AWAY_MISSING_OR_UNSUBMITTED')
    for side in ('injury_home','injury_away'):
        if bench[side].get('status_counts',{}).get('Questionable',0)>0 or bench[side].get('status_counts',{}).get('Doubtful',0)>0:
            issues.append('UNCERTAIN_PLAYERS')
    issues.append('MODEL_NOT_BACKTEST_CALIBRATED')
    issues.append('INJURY_IMPACT_NOT_QUANTIFIED')
    return list(dict.fromkeys(issues))

def estimate(home,away,standings,eff,last,inj,league_avg):
    hs=standings[home[1]];as_=standings[away[1]]
    he=eff[home[1]];ae=eff[away[1]]
    n1,n2=he['sample_games'],ae['sample_games']
    # Pace and pace-adjusted scoring are *estimated* from small boxscore samples.
    # Shrink all ratings toward the sample league means to prevent overfitting.
    off0=league_avg['off'];def0=league_avg['def'];pace0=league_avg['pace']
    shrink=lambda v,center,n:center+(v-center)*(n/(n+12))
    ho=shrink(he['off_rating'],off0,n1);hd=shrink(he['def_rating'],def0,n1)
    ao=shrink(ae['off_rating'],off0,n2);ad=shrink(ae['def_rating'],def0,n2)
    pace=(shrink(he['pace_estimate'],pace0,n1)+shrink(ae['pace_estimate'],pace0,n2))/2
    # Symmetric default home edge 2 points, empirical calibration missing.
    home_pts=pace*(ho+ad)/200+1
    away_pts=pace*(ao+hd)/200-1
    recent={}
    for label,name in (('home',home[1]),('away',away[1])):
        games=last.get(name,[])[:5]
        recent[label]={
            'last_n':len(games),
            'last_n_wins':sum(bool(g.get('win')) for g in games),
            'latest_tipoff_utc':games[0]['kickoff'] if games else None,
            'scored_recent_mean':(sum(g['points'] for g in games)/len(games)) if games else None,
            'conceded_recent_mean':(sum(g['opponent_points'] for g in games)/len(games)) if games else None
        }
    meta={
        'efficiency_games_home':n1,'efficiency_games_away':n2,
        'standings_games_home':hs['games_played'],'standings_games_away':as_['games_played'],
        'home_efficiency':he,'away_efficiency':ae,
        'form_home':recent['home'],'form_away':recent['away'],
        'injury_home':inj.get(home[1],{'report_state':'NOT_LISTED','players':[],'status_counts':{}}),
        'injury_away':inj.get(away[1],{'report_state':'NOT_LISTED','players':[],'status_counts':{}})
    }
    return {
        'pace_mean':pace,'home_points_mean':home_pts,'away_points_mean':away_pts,
        'home_margin_mean':home_pts-away_pts,'total_points_mean':home_pts+away_pts,
        'margin_sigma_assumed':16.5,'total_sigma_assumed':22.5,
        'home_advantage_points_assumed':2.0,
        'uncertainty':'UNVALIDATED Gaussian score distribution, approximate possessions; result is exploratory only',
        'meta':meta,
    }

def evaluate_board(joined,injury,effdata,standingdata,recentdata):
    standings={x['team_name']:x for x in standingdata['teams']}
    efficiency=effdata['teams']
    recent=recentdata['teams']
    valid=[x for x in efficiency.values() if x.get('sample_games',0)>0]
    league_avg={
      'off':sum(x['off_rating']*x['sample_games'] for x in valid)/sum(x['sample_games'] for x in valid),
      'def':sum(x['def_rating']*x['sample_games'] for x in valid)/sum(x['sample_games'] for x in valid),
      'pace':sum(x['pace_estimate']*x['sample_games'] for x in valid)/sum(x['sample_games'] for x in valid),
    }
    matches=[]
    errors=[]
    for g in joined['nba_cba_games']:
        if g['league']!='NBA':continue
        mid=g['game_id']
        try:
            home=NAMES[g['home_team']];away=NAMES[g['away_team']]
            matchup=away[0]+'@'+home[0]
            if home[1] not in standings or away[1] not in standings:raise ValueError('Standings missing')
            if home[1] not in efficiency or away[1] not in efficiency:raise ValueError('Efficiency sample missing')
            injury_map=injury.get('matchups',{}).get(matchup,{})
            model=estimate(home,away,standings,efficiency,recent,injury_map,league_avg)
            meta=model.pop('meta')
            blocks=quality(g,meta)
            market_data={}
            for market in ('full_spread','full_total'):
                raw=g['markets'].get(market,{})
                entry={'market':market,'opening':{},'current':{}}
                for stage in ('opening','current'):
                    data=raw.get(stage,{})
                    line=data.get('line');w1=data.get('first_side_water');w2=data.get('second_side_water')
                    if line is None or w1 is None or w2 is None:
                        entry[stage]={'status':'MISSING_MARKET'};continue
                    mu=model['home_margin_mean'] if market=='full_spread' else model['total_points_mean']
                    sd=model['margin_sigma_assumed'] if market=='full_spread' else model['total_sigma_assumed']
                    v=mathodds.evaluate(float(line),float(w1),float(w2),mu,sd)
                    v['status']='MARKET_CALCULATED_EXPERIMENTAL'
                    v['side_labels']='home_cover_vs_away_cover' if market=='full_spread' else 'over_vs_under'
                    entry[stage]=v
                market_data[market]=entry
            matches.append({
                'game_id':mid,'league':g['league'],'date':g['display_date'],
                'display_clock':g['display_clock'],'home_team':g['home_team'],'away_team':g['away_team'],
                'matchup_code':matchup,
                'model':model,'availability':{
                    'home':meta['injury_home'],'away':meta['injury_away'],
                    'source_pdf':injury.get('source_url'),'source_date':injury.get('report_et_date')},
                'recent_form':{'home':meta['form_home'],'away':meta['form_away']},
                'markets':market_data,
                'quality_blocks':blocks,
                'bet_action':'NO_BET',
                'value_classification':'EXPERIMENTAL_DIAGNOSTIC_ONLY'
            })
        except Exception as e:
            errors.append({'game_id':mid,'error':type(e).__name__+':'+str(e)[:160]})
    out={
        'analysed_at_utc':datetime.now(timezone.utc).isoformat(),
        'date':joined['requested_display_date'],
        'source_market':joined['odds_source'],
        'source_schedule':joined['score_source'],
        'source_injury_pdf':injury.get('source_url'),
        'source_efficiency':'StatsHawk confirmed player boxscores (last 2 per team)',
        'source_last_games':'StatsHawk confirmed recent matches',
        'company':'Crow* (3): matched 6/6 quoted spread/total snapshots in prior quality test',
        'market_orientation':'first spread water = home cover, raw positive line = home gives; first total water = over; verified by independent matchup handicap sign, but direct side headers unlabelled',
        'probability_grade':'EXPERIMENTAL_NOT_CALIBRATED',
        'policy':'Never issue positive-value betting recommendation without out-of-sample calibration, sufficient team and player availability data',
        'league_sample_prior':league_avg,
        'game_count':len(matches),'games':matches,'errors':errors,
        'recommended_bets':[],
        'notes':['Current NBA teams have 3-4 games of season record and 2 boxscore efficiency samples; do not treat estimated EV as a proven edge.',
                 'Injury statuses linked to exact matchup; NOT_SUBMITTED or Questionable is not presumed playable.',
                 'Public 007 Crow* displayed odds can differ from actual account executable offers.'],
    }
    return out

def self_test():
    assert NAMES['亚特兰大老鹰'][0]=='ATL'
    assert NAMES['迈阿密热火'][0]=='MIA'
    assert quality({'league':'NBA'},{'efficiency_games_home':2,'efficiency_games_away':2,'standings_games_home':4,'standings_games_away':4,'injury_home':{'report_state':'PUBLISHED'},'injury_away':{'report_state':'PUBLISHED'}})[0]=='EARLY_SEASON_LOW_SAMPLE'
    print('EXPERIMENTAL_EV_TEST_PASS')

def render_csv(report,path):
    headers=['date','game_id','home','away','market','line','water1','water2','decimal1','decimal2','devig1','devig2','exp_ev1','exp_ev2','issues']
    with open(path,'w',newline='',encoding='utf-8-sig') as f:
        w=csv.writer(f);w.writerow(headers)
        for g in report['games']:
            for market in ('full_spread','full_total'):
                d=g['markets'][market]['current']
                if d.get('status')!='MARKET_CALCULATED_EXPERIMENTAL':continue
                w.writerow([g['date'],g['game_id'],g['home_team'],g['away_team'],market,
                    d['line'],g['markets'][market]['opening'].get('line'),d['decimal_side1']-1,d['decimal_side2']-1,
                    d['decimal_side1'],d['decimal_side2'],
                    round(d['no_vig_conditional_side1'],6),round(d['no_vig_conditional_side2'],6),
                    round(d['diagnostic_ev_side1'],6),round(d['diagnostic_ev_side2'],6),';'.join(g['quality_blocks'])])

def render_html(report,path):
    esc=lambda x:html.escape(str(x))
    cards=[]
    for g in report['games']:
        m=g['model'];rows=[]
        for market,label in (('full_spread','让分'),('full_total','总分')):
            x=g['markets'][market]['current']
            if x.get('status')!='MARKET_CALCULATED_EXPERIMENTAL':continue
            rows.append(f'<tr><td>{label}</td><td>{x["line"]:g}</td><td>{x["no_vig_conditional_side1"]*100:.1f}% / {x["no_vig_conditional_side2"]*100:.1f}%</td><td>{x["diagnostic_ev_side1"]*100:+.1f}% / {x["diagnostic_ev_side2"]*100:+.1f}%</td></tr>')
        h=g['availability']['home'];a=g['availability']['away']
        summary=lambda z:f'{z.get("report_state","UNKNOWN")} · 缺阵 {z.get("status_counts",{}).get("Out",0)} · 待确认 {z.get("status_counts",{}).get("Questionable",0)}'
        cards.append(f'''<section><div class="meta">{esc(g["date"])} {esc(g["display_clock"])} · #{esc(g["game_id"])}</div>
<h3>{esc(g["home_team"])} vs {esc(g["away_team"])}</h3>
<p>模型示例：主 {m["home_points_mean"]:.1f} / 客 {m["away_points_mean"]:.1f} · 总分 {m["total_points_mean"]:.1f} · 预计节奏 {m["pace_mean"]:.1f}</p>
<table><thead><tr><th>盘口</th><th>皇冠即时</th><th>去水概率（两侧）</th><th>试算 EV（两侧）</th></tr></thead><tbody>{''.join(rows)}</tbody></table>
<p class="small">伤停：主队 {esc(summary(h))}；客队 {esc(summary(a))}</p>
<p class="warning">不下注：{esc(', '.join(g['quality_blocks']))}</p></section>''')
    css='''body{background:#f7f8fa;color:#19283f;font:14px -apple-system,BlinkMacSystemFont,sans-serif;max-width:950px;margin:0 auto;padding:16px}
h1{font-size:24px}h3{font-size:17px}section{background:white;padding:15px;border:1px solid #ddd;border-radius:14px;margin-bottom:12px}
.meta,.small{color:#66778a;font-size:12px}p{line-height:1.5}table{width:100%;border-collapse:collapse;font-size:11px;table-layout:fixed}td,th{padding:7px 4px;text-align:left;border-bottom:1px solid #e6e8ec;word-break:break-word}
.warning{font-size:11px;color:#9b4a30} .top{background:#fff;border:1px solid #ddd;border-radius:12px;padding:14px;margin:14px 0}'''
    doc=f'''<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>NBA 皇冠盘口概率研究</title><style>{css}</style></head>
<body><h1>NBA 皇冠盘口概率研究</h1><div class="top"><b>2026-10-29 · {len(report["games"])} 场</b>
<p>全部标记“不下注”：当前赛季样本极小，效率仅基于近两场技术统计，伤停影响没有量化，模型未经历史回测校准。</p>
<p>归一化去水概率是市场基准；试算 EV 是粗模型情景，不是已经验证的获利机会。让分正号表示主队让分。先核实自己的可成交盘口。</p>
<p>官方伤停：{esc(report["source_injury_pdf"])}</p></div>{''.join(cards)}</body></html>'''
    Path(path).write_text(doc,encoding='utf-8')

if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--test',action='store_true')
    p.add_argument('--joined',default='titan007_joined_nba_cba.json')
    p.add_argument('--injuries',default='nba_official_injuries.json')
    p.add_argument('--data-dir',default='analysis/data')
    p.add_argument('--out',default='nba_market_value_analysis.json')
    a=p.parse_args()
    if a.test:self_test();raise SystemExit(0)
    dir=Path(a.data_dir)
    output=evaluate_board(load(a.joined),load(a.injuries),
        load(dir/'nba_2026_10_28_efficiency_sample.json'),
        load(dir/'nba_2026_10_28_team_form_snapshot.json'),
        load(dir/'nba_2026_10_28_last_games.json'))
    if output['errors'] or output['game_count']<1:raise RuntimeError('Unmatched game data: '+str(output['errors']))
    Path(a.out).write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8')
    render_csv(output,'nba_market_value_analysis.csv')
    render_html(output,'nba_market_value_analysis.html')
    print(json.dumps({'analysed':output['game_count'],'errors':output['errors'],
        'bets':len(output['recommended_bets']),'quality':'EXPERIMENTAL',
        'examples':[{'id':g['game_id'],'matchup':g['matchup_code'],
                     'model_total':round(g['model']['total_points_mean'],2),
                     'current_total':g['markets']['full_total']['current'].get('line'),
                     'current_total_devig':round(g['markets']['full_total']['current'].get('no_vig_conditional_side1',0),4),
                     'current_total_ev_over':round(g['markets']['full_total']['current'].get('diagnostic_ev_side1',0),4),
                     'injury_home_state':g['availability']['home'].get('report_state')} for g in output['games'][:6]]},ensure_ascii=False,indent=2))
