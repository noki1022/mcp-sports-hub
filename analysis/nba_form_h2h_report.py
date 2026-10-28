#!/usr/bin/env python3
"""Mobile-friendly NBA rolling form and H2H report from independently verified CSV results."""
from __future__ import annotations
import argparse,csv,html,json
from pathlib import Path
def write(source,out="nba_recent_form_h2h.html"):
    data=json.loads(Path(source).read_text(encoding="utf-8"))
    E=lambda x:html.escape(str(x))
    blocks=[]
    for g in data["nba_games"]:
        if g.get("status")=="UNMAPPED_TEAM":
            blocks.append("<section><h3>无法匹配球队</h3><p>该场比赛未纳入统计，未编造数据。</p></section>")
            continue
        form=[]
        for side,title in (("home_recent","主队"),("away_recent","客队")):
            f=g[side]
            games=f.get("last_five",[])
            games_rows="".join(f'<tr><td>{E(x["date"])}</td><td>{E(x["opponent"])}</td><td>{E(x["site"])}</td><td>{E(x["result"])}</td><td>{x["points"]}–{x["opp_points"]}</td></tr>' for x in games)
            form.append(f'<h4>{title}近 {len(games)} 场：{f.get("wins_last_five",0)} 胜</h4>'
                f'<p>得分 {f.get("points_per_game","—")} / 失分 {f.get("opponent_points_per_game","—")}，'
                f'估算百回合进攻 {f.get("off_rating_100pos_est","—")} / 防守 {f.get("def_rating_100pos_est","—")}，'
                f'回合数 {f.get("possessions_per_game_est","—")}</p>'
                f'<table><thead><tr><th>日期</th><th>对手</th><th>主客</th><th>结果</th><th>比分</th></tr></thead><tbody>{games_rows}</tbody></table>')
        h2h=g["head_to_head"]
        hist="".join(f'<tr><td>{E(x["date"])}</td><td>{E(x["home"])}–{E(x["away"])}</td><td>{E(x["score"])}</td><td>{x["total"]}</td></tr>' for x in h2h["recent_five"])
        blocks.append(f'''<section><div class="muted">#{E(g["game_id"])} · {E(g["status"])}</div>
          <h3>{E(g["home"])} vs {E(g["away"])}</h3>{''.join(form)}
          <h4>双方近 {h2h["verified_h2h_games"]} 次交锋</h4><p>本场主队过去 {h2h["verified_h2h_games"]} 次交锋赢 {h2h["home_team_past_wins"]} 次</p>
          <table><thead><tr><th>日期</th><th>对阵</th><th>比分</th><th>总分</th></tr></thead><tbody>{hist}</tbody></table>
          <p class="muted">历史数据仅作参考；历史交锋横跨不同赛季，球员名单可能变化。不代表实际投注价值。</p>
          </section>''')
    doc='''<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<style>body{margin:0 auto;max-width:920px;padding:15px;background:#f5f6f9;color:#233348;font-family:-apple-system,BlinkMacSystemFont,sans-serif}
section{background:white;padding:16px;border:1px solid #e2e6ec;border-radius:14px;margin:12px 0}
h1{font-size:22px}h3{font-size:17px}h4{font-size:14px;margin-bottom:6px}p{font-size:12px;line-height:1.6}
.muted{color:#697a8d;font-size:11px}table{font-size:11px;border-collapse:collapse;width:100%;table-layout:fixed}td,th{text-align:left;padding:7px 3px;border-bottom:1px solid #ecedf0;word-wrap:break-word}</style></head><body>
<h1>NBA 每日近五场、攻防效率和历史交锋</h1>
<p>目标比赛日期：__DATE__。所有用于统计的比赛均早于比赛日期，且双方比分已交叉核对。进攻/防守每百回合为根据技术统计估算值，不是官方高级统计。</p>
__CARDS__
</body></html>'''
    doc=doc.replace("__DATE__",E(data["target_date"])).replace("__CARDS__","\n".join(blocks))
    Path(out).write_text(doc,encoding="utf-8")
    csvpath=Path(out).with_suffix(".csv")
    with csvpath.open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.writer(f);w.writerow(["game_id","home","away","home_last5","away_last5","home_last5_wins","away_last5_wins","home_off100","home_def100","away_off100","away_def100","h2h_last5","home_h2h_wins","status"])
        for g in data["nba_games"]:
            if g.get("status")=="UNMAPPED_TEAM":continue
            h,a=g["home_recent"],g["away_recent"];h2h=g["head_to_head"]
            w.writerow([g["game_id"],g["home"],g["away"],h["sample_games"],a["sample_games"],h["wins_last_five"],a["wins_last_five"],h["off_rating_100pos_est"],h["def_rating_100pos_est"],a["off_rating_100pos_est"],a["def_rating_100pos_est"],h2h["verified_h2h_games"],h2h["home_team_past_wins"],g["status"]])
    print("FORM_H2H_REPORT_WRITTEN",len(blocks),out,str(csvpath))
if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--source",default="nba_recent_form_h2h.json")
    p.add_argument("--out",default="nba_recent_form_h2h.html")
    a=p.parse_args()
    write(a.source,a.out)
