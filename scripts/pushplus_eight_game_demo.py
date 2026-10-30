#!/usr/bin/env python3
"""One-time eight-game fictional PushPlus HTML preview. Never a real pick."""
from __future__ import annotations
import json,os,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from pushplus_mobile import send,save_status,txt
TEAMS=[
("07:00","波士顿凯尔特人","纽约尼克斯",-4.5,-5.5,223.5,226.0,0.64,115,109,"主队攻防综合优势；让分加深，需警惕盘口过热","中"),
("07:30","克利夫兰骑士","迈阿密热火",-6.5,-5.0,216.5,214.5,0.68,109,103,"主胜倾向仍在，但让分退盘说明预期优势收窄","中高"),
("08:00","密尔沃基雄鹿","印第安纳步行者",-2.5,-3.5,235.5,240.0,0.59,124,119,"双方节奏偏快；总分上调幅度明显","高"),
("08:00","芝加哥公牛","亚特兰大老鹰",1.5,2.5,230.5,227.5,0.44,111,115,"客胜概率略高，总分下调提示节奏预期转弱","中"),
("08:30","达拉斯独行侠","休斯敦火箭",3.5,1.5,222.5,224.5,0.47,112,114,"让分朝主队方向变化但模型仍微倾客队，分歧较大","高"),
("09:00","丹佛掘金","明尼苏达森林狼",-3.5,-4.5,217.5,216.0,0.62,111,106,"主队实力优势较稳；低总分环境下让分容错偏小","中"),
("10:00","菲尼克斯太阳","洛杉矶湖人",1.5,-1.5,231.5,234.5,0.55,119,115,"让分跨越零点，市场方向发生显著变化","高"),
("10:30","金州勇士","萨克拉门托国王",-5.5,-4.0,238.5,236.0,0.66,121,115,"主胜概率较高，但让分退盘与模型优势并不同步","中高")
]
def card(i,d):
    time,home,away,sp0,sp1,t0,t1,p,hs,as_,reason,risk=d
    shift_sp=sp1-sp0;shift_t=t1-t0
    line=lambda text:"<div style='margin:7px 0;font-size:14px;line-height:1.7;'>"+text+"</div>"
    tag=(" <span style='font-size:11px;color:#9c4a21;background:#fff2e8;padding:2px 6px;border-radius:4px;'>"+txt(risk)+"风险</span>")
    s=f"<div style='margin:12px 0;padding:13px;border:1px solid #e4eaf1;border-radius:12px;background:#fff;'>"
    s+=f"<div style='font-size:12px;color:#607184;'>#{i:02d} · {time} 北京时间 · NBA · 模拟</div>"
    s+=f"<div style='font-size:17px;font-weight:700;color:#15243b;margin:5px 0;'>{txt(home)}<br/>VS {txt(away)}{tag}</div>"
    s+=f"<div style='padding:9px 10px;background:#f1f5fa;border-radius:7px;'><span style='font-size:12px;color:#526479;'>模拟预测比分</span><div style='font-size:21px;font-weight:700;'>{hs} : {as_} <span style='font-size:12px;font-weight:400;'>主胜概率 {p:.0%}</span></div></div>"
    s+=line(f"<b>全场让分：</b>{sp0:+.1f} → {sp1:+.1f}　<span style='color:#526479;'>变化 {shift_sp:+.1f}</span>")
    s+=line(f"<b>全场总分：</b>{t0:.1f} → {t1:.1f}　<span style='color:#526479;'>变化 {shift_t:+.1f}</span>")
    s+=line(f"<b>模拟模型：</b>主胜 {p:.0%} / 客胜 {1-p:.0%}；预测总分 {hs+as_}，预测分差 {hs-as_:+d}")
    s+=line("<span style='color:#44556a;'><b>综合研判：</b>"+txt(reason)+"。</span>")
    s+=f"<div style='border-top:1px solid #e6ebf2;margin-top:8px;padding-top:8px;font-size:12px;color:#66758a;'>仅排版展示 · 未使用真实盘口 · 非投注建议</div></div>"
    return s
def build():
    head="<div style='font-family:-apple-system,BlinkMacSystemFont,Arial,sans-serif;max-width:540px;margin:0 auto;color:#203047;font-size:14px;'>"
    head+="<div style='background:#eaf1fa;padding:14px;border-radius:12px;'><div style='font-size:20px;font-weight:800;'>NBA 八场模型分析</div><div style='font-size:13px;color:#425a77;margin-top:3px;'>2026-10-31 · 北京时间 · 8 场模拟演示</div><div style='font-size:12px;color:#97531c;margin-top:7px;'><b>⚠ 全部为虚构对阵与模拟赔率，仅测试 iPhone 推送排版</b></div></div>"
    head+="<div style='padding:12px 4px 5px;font-weight:700;'>八场速览</div>"
    for i,d in enumerate(TEAMS,1):
        time,home,away,sp0,sp1,t0,t1,p,hs,as_,reason,risk=d
        head+=f"<div style='font-size:13px;border-bottom:1px solid #e8edf3;padding:7px 4px;'>#{i:02d}　{time}　{txt(home)} / {txt(away)}<br/><span style='color:#607184;'>主胜 {p:.0%}　预测 {hs}:{as_}　风险 {risk}</span></div>"
    head+="<div style='margin:15px 2px 5px;font-size:16px;font-weight:700;'>逐场模型与盘口波动</div>"
    return head+"".join(card(i,x) for i,x in enumerate(TEAMS,1))+"<div style='color:#66758a;font-size:12px;margin:16px 2px;'>本消息全部数据为虚构模拟，不代表实际 NBA 赛程、报价、球员状态或可投注建议。</div></div>"
def main():
    out=Path("/tmp/pushplus-eight-demo.html")
    html=build()
    out.write_text(html,encoding="utf-8")
    if len(TEAMS)!=8 or html.count("仅排版展示")!=8:raise RuntimeError("EIGHT_GAME_LAYOUT_INVALID")
    print("PUSHPLUS_EIGHT_DEMO_LAYOUT_PASS",len(html.encode("utf-8")),"bytes",flush=True)
    if "--send" in sys.argv:
        result=send({"title":"【纯模拟】NBA 8 场盘口＋模型报告｜排版测试","html":html},os.environ.get("PUSHPLUS_TOKEN",""))
        save_status("/tmp/pushplus-eight-demo-status.json",{"type":"one_time_eight_game_demo","synthetic":True,**result})
        print("PUSHPLUS_EIGHT_DEMO_SEND",result["state"],flush=True)
if __name__=="__main__":main()
