#!/usr/bin/env python3
"""Explicitly authorized single fictional 8-game V2 PushPlus demonstration."""
import json,os,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from pushplus_mobile_v2 import render_v2
from pushplus_mobile import send,save_status
gamespec=[
("07:00","波士顿凯尔特人","纽约尼克斯",-4.5,-5.5,223.5,226.0,.64,6,224),
("07:30","克利夫兰骑士","迈阿密热火",-6.5,-5,216.5,214.5,.68,6,212),
("08:00","密尔沃基雄鹿","印第安纳步行者",-2.5,-3.5,235.5,240,.59,5,243),
("08:00","芝加哥公牛","亚特兰大老鹰",1.5,2.5,230.5,227.5,.44,-4,226),
("08:30","达拉斯独行侠","休斯敦火箭",3.5,1.5,222.5,224.5,.47,-2,226),
("09:00","丹佛掘金","明尼苏达森林狼",-3.5,-4.5,217.5,216,.62,5,217),
("10:00","菲尼克斯太阳","洛杉矶湖人",1.5,-1.5,231.5,234.5,.55,4,234),
("10:30","金州勇士","萨克拉门托国王",-5.5,-4,238.5,236,.66,6,236)]
games=[];models={}
for i,(clock,home,away,op,now,ot,nt,ph,margin,total) in enumerate(gamespec,1):
    gid=str(800000+i)
    market=lambda o,n,shift:{"opening":{"line":o},"previous":{"line":n-shift},"current":{"line":n},"first_snapshot":{"line":o},"delta_line_previous":shift}
    games.append({"game_id":gid,"league":"NBA","display_clock":clock,"home_team":home,"away_team":away,
        "status":"LINE_MOVE" if i%2 else "LINE_AND_WATER_MOVE",
        "markets":{"full_spread":market(op,now,-.5 if i%2 else .5),
                   "full_total":market(ot,nt,1 if i%2 else -1)}})
    models[gid]={"model_status":"OK","model_probability":{"home":ph,"away":1-ph},
                 "margin_mean_home_minus_away":margin,"total_mean":total,
                 "data_quality":{"quality":"PASS"}}
html=render_v2(games,models,"【全模拟】NBA 八场 V2 排版测试","2026-10-31","hourly")
html="<div style='font-size:13px;padding:10px;background:#fff4e7;color:#934500;font-weight:bold;'>仅排版测试：8场球队对阵、比分预测、模型概率及盘口均为虚构，非真实比赛分析、非投注建议。</div>"+html
assert len(games)==8 and html.count("NO_BET")>=8 and "比赛速览" in html
Path("/tmp/nba-v2-eight-preview.html").write_text(html,encoding="utf-8")
print("V2_EIGHT_SIMULATION_LAYOUT_PASS",len(html.encode("utf-8")),flush=True)
result=send({"title":"【全模拟】NBA 8场 V2 模型与盘口报告｜排版测试","html":html},os.environ.get("PUSHPLUS_TOKEN",""))
save_status("/tmp/nba-v2-eight-status.json",{"synthetic":True,"count":8,**result})
print("V2_EIGHT_PUSHPLUS_RESULT",result["state"],flush=True)
