#!/usr/bin/env python3
"""Render checked Titan007 basketball daily snapshot as CSV and mobile-friendly HTML."""
from __future__ import annotations
import argparse,csv,json,html
from pathlib import Path

FIELDS=[
    "league","display_date","display_clock","home_team","away_team","game_id",
    "spread_open_line","spread_now_line",
    "spread_open_water_1","spread_open_water_2","spread_now_water_1","spread_now_water_2",
    "total_open_line","total_now_line",
    "total_open_water_1","total_open_water_2","total_now_water_1","total_now_water_2"
]
def get(g,market,phase,field):
    return g.get("markets",{}).get(market,{}).get(phase,{}).get(field)

def rows_for(data):
    rows=[]
    for g in data.get("nba_cba_games",[]):
        d={k:g.get(k,"") for k in FIELDS[:6]}
        for name,label in (("full_spread","spread"),("full_total","total")):
            for stage, alias in (("opening","open"),("current","now")):
                d[f"{label}_{alias}_line"]=get(g,name,stage,"line")
                for num,slot in ((1,"first_side_water"),(2,"second_side_water")):
                    d[f"{label}_{alias}_water_{num}"]=get(g,name,stage,slot)
        rows.append(d)
    return rows

def fmt(v):
    if v is None or v=="":return "—"
    return str(v)

def render(data,quality,csv_path,html_path):
    rows=rows_for(data)
    with open(csv_path,"w",newline="",encoding="utf-8-sig") as f:
        writer=csv.DictWriter(f,fieldnames=FIELDS,extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    checks=quality.get("matching_markets",0) if quality else 0
    misses=quality.get("mismatching_markets",0) if quality else 0
    missing=quality.get("unverified_markets",0) if quality else 0
    status=(f"Crow* 公开单场样本核对 {checks} / {checks+misses+missing}，差异 {misses}"
            if quality else "未执行公开单场 Crown 样本核验")
    cards=[]
    for r in rows:
        esc=lambda x:html.escape(fmt(x))
        cards.append(f'''<section class="match">
          <div class="top"><span class="league">{esc(r["league"])} · {esc(r["display_date"])} {esc(r["display_clock"])}</span><code>#{esc(r["game_id"])}</code></div>
          <div class="teams"><strong>{esc(r["home_team"])}</strong><span>vs</span><strong>{esc(r["away_team"])}</strong></div>
          <div class="market"><span>让分</span><strong>{esc(r["spread_open_line"])} → {esc(r["spread_now_line"])}</strong>
            <small>初水 {esc(r["spread_open_water_1"])} / {esc(r["spread_open_water_2"])} · 即水 {esc(r["spread_now_water_1"])} / {esc(r["spread_now_water_2"])}</small></div>
          <div class="market"><span>总分</span><strong>{esc(r["total_open_line"])} → {esc(r["total_now_line"])}</strong>
            <small>初水 {esc(r["total_open_water_1"])} / {esc(r["total_open_water_2"])} · 即水 {esc(r["total_now_water_1"])} / {esc(r["total_now_water_2"])}</small></div>
          </section>''')
    template='''<!doctype html><html lang="zh"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>007 NBA/CBA 公共盘口采样</title><style>
:root{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:#15233a;background:#f5f7fb}
body{max-width:830px;margin:0 auto;padding:20px 14px 60px}h1{font-size:24px;margin:0 0 12px}
.subtitle{color:#69768a;font-size:13px}.notice{background:white;border:1px solid #d9e1ec;border-radius:12px;padding:14px;line-height:1.7;font-size:13px;margin:18px 0}
.match{background:white;border:1px solid #e4e8f0;border-radius:14px;padding:16px;margin:12px 0;box-shadow:0 2px 6px #00000006}
.top{display:flex;justify-content:space-between;gap:8px;color:#58677d;font-size:12px}.top code{color:#71839a}
.teams{display:flex;justify-content:space-between;align-items:center;gap:7px;font-size:15px;margin:15px 0 12px}
.teams span{color:#9aacc2;font-size:12px}.teams strong{flex:1}.teams strong:last-child{text-align:right}
.market{border-top:1px solid #edf0f5;padding-top:9px;margin-top:8px;display:grid;grid-template-columns:55px 1fr;align-items:center}
.market span{font-size:13px;color:#68788b}.market strong{font-size:18px;text-align:right;font-variant-numeric:tabular-nums}
.market small{grid-column:1/-1;text-align:right;color:#68788b;margin-top:4px;font-size:12px}
</style></head><body><h1>007 NBA / CBA 盘口快照</h1>
<div class="subtitle">网站展示日期：DATE ｜ 匹配比赛：COUNT ｜ 采样时间 UTC：CAPTURED</div>
<div class="notice"><strong>质量状态：</strong>QUALITY<br>
公开赛程和批量盘口以比赛 ID 关联。盘口数值属于 Crow* 来源样本核对，不代表每场都逐条核验。
让分正负符号及左右水位含义仍按网站原始格式保留，未作下注方向转换；
比赛时刻为 007 展示时刻，尚未独立核实其时区。此报表不包含预测或投注建议。</div>
CARDS
</body></html>'''
    for token,replacement in {
        "DATE":data.get("requested_display_date",""),
        "COUNT":str(len(rows)),
        "CAPTURED":data.get("captured_at_utc",""),
        "QUALITY":status,
        "CARDS":"\n".join(cards) or "<p>目标日期无已匹配比赛</p>"
    }.items():
        template=template.replace(token,html.escape(replacement) if token!="CARDS" else replacement)
    Path(html_path).write_text(template,encoding="utf-8")
    print(json.dumps({"report_html":html_path,"report_csv":csv_path,"matches":len(rows),"quality":status},ensure_ascii=False))
    if not rows:
        print("NO_MATCHES: no NBA/CBA markets joined for target display date")

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--joined",default="titan007_joined_nba_cba.json")
    p.add_argument("--quality",default="titan007_crown_quality_check.json")
    p.add_argument("--html",default="titan007_nba_cba_report.html")
    p.add_argument("--csv",default="titan007_nba_cba_report.csv")
    args=p.parse_args()
    data=json.loads(Path(args.joined).read_text(encoding="utf-8"))
    quality=json.loads(Path(args.quality).read_text(encoding="utf-8")) if Path(args.quality).exists() else None
    render(data,quality,args.csv,args.html)
