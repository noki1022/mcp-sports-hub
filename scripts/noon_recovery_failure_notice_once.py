#!/usr/bin/env python3
"""One-time source failure notification; no forecast or fake match data."""
import json,os,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from pushplus_mobile import send,save_status
p=Path("titan007_three_joined.json")
v=json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
n=int(v.get("nba_cba_joined_for_date",0))
if n!=0:
    print("SOURCE_NOT_EMPTY_NO_FAILURE_NOTICE",n)
    raise SystemExit(0)
title="【数据异常】10月31日 NBA 午间报告未生成"
html=("<div style='font-family:-apple-system,BlinkMacSystemFont,Arial,sans-serif;max-width:520px;margin:auto;line-height:1.7;'>"
"<div style='padding:12px;background:#fff0df;border-radius:10px;font-size:18px;font-weight:700;'>"
"10月31日赛前数据暂不可用</div>"
"<p>北京时间10月30日12:00及12:30定时分析未正常触发；手动补跑后，Titan007 当前来源匹配到 <b>0 场</b> NBA/CBA 盘口。</p>"
"<p>这不代表没有比赛。NBA 官方赛程仍列有比赛；本次未生成未经验证的赔率或模型预测。</p>"
"<p><b>状态：</b>数据源匹配异常 · 盘口分析暂停 · NO_BET</p>"
"<p style='font-size:12px;color:#6b7b8d;'>这是一条真实系统故障通知，不是模拟推送，也不是投注建议。</p></div>")
result=send({"title":title,"html":html},os.environ.get("PUSHPLUS_TOKEN",""))
save_status("/tmp/noon-recovery-error-status.json",{"type":"SOURCE_ZERO_GAMES_ALERT",**result})
print("NOON_RECOVERY_ALERT",result["state"])
