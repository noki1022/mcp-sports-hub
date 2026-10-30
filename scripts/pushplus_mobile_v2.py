"""V2 compact, data-grounded PushPlus HTML report for NBA/CBA."""
from __future__ import annotations
import math
from html import escape

def num(x):
    try:
        v=float(x)
        return v if math.isfinite(v) else None
    except (TypeError,ValueError):return None
def f(x,signed=False):
    v=num(x)
    return "—" if v is None else (f"{v:+.1f}" if signed else f"{v:.1f}")
def text(x):
    return escape(str(x if x is not None else "—"),quote=True)
def cell(body):
    return "<div style='padding:9px 10px;margin:5px 0;border:1px solid #e4eaf0;border-radius:8px;'>"+body+"</div>"
def para(body):
    return "<div style='font-size:13px;line-height:1.6;margin:5px 0;color:#26384e;'>"+body+"</div>"
def market_change(m,kind):
    q=m.get("current") or {}
    opening=m.get("opening") or {}
    previous=m.get("previous") or {}
    first=m.get("first_snapshot") or {}
    label="让分" if kind=="full_spread" else "总分"
    current=num(q.get("line"))
    prior=num(previous.get("line"))
    op=num(opening.get("line"))
    base=num(first.get("line"))
    return (
        para("<b>"+label+"</b>　初 "+f(op)+" → 现 <b>"+f(current)+"</b>")+
        para("上次 "+f(prior)+"｜近次 Δ "+f(current-prior if current is not None and prior is not None else None,True)+
             "｜首快照 Δ "+f(current-base if current is not None and base is not None else None,True)))
def score_prediction(pred):
    if not pred or pred.get("model_status") not in ("OK","PARTIAL"):
        return para("独立模型：缺失或不可用，不生成预测比分")
    total=num(pred.get("total_mean"))
    margin=num(pred.get("margin_mean_home_minus_away"))
    if total is None or margin is None:return para("独立模型：总分或分差数据缺失")
    hp=(total+margin)/2
    ap=(total-margin)/2
    if hp<0 or ap<0:return para("独立模型：预测值异常")
    p=(pred.get("model_probability") or {}).get("home")
    prob="—" if num(p) is None or not 0<=num(p)<=1 else f"{num(p)*100:.1f}%"
    return para("<b>模型估计</b>　主 "+f(hp)+" : "+f(ap)+" 客｜主胜 "+prob+
                "｜净胜 "+f(margin,True)+"｜总分 "+f(total))
def compare(pred, spread, total):
    if not pred:return para("模型与盘口差：无可用模型")
    margin=num(pred.get("margin_mean_home_minus_away"))
    t=num(pred.get("total_mean"))
    curr_spread=num((spread.get("current") or {}).get("line"))
    curr_total=num((total.get("current") or {}).get("line"))
    # Signed line orientation is NOT certified: do not label raw line difference as a betting edge.
    parts=[]
    if curr_spread is not None and margin is not None:
        parts.append("模型主队净胜 "+f(margin,True)+"；原始让分 "+f(curr_spread,True)+"（方向未核验，差值不可判定）")
    if curr_total is not None and t is not None:
        parts.append("模型总分与盘口差 "+f(t-curr_total,True)+" 分（非覆盖概率）")
    return para("；".join(parts) if parts else "模型与盘口差：字段不完整")
def confidence(pred,move):
    if not pred or pred.get("model_status") not in ("OK","PARTIAL"):
        return "数据不足"
    q=pred.get("data_quality") or {}
    qual=q.get("quality") if isinstance(q,dict) else None
    if qual not in ("PASS","GOOD"):return "模型样本待核验"
    if move.get("status")=="FIRST_SNAPSHOT":return "首次采样"
    return "盘口方向待核验"
def signal(g):
    moves=g.get("markets") or {}
    n=sum(abs(num((moves.get(k) or {}).get("delta_line_previous")) or 0) for k in ("full_spread","full_total"))
    return n+(2 if g.get("status") in ("LINE_AND_WATER_MOVE","LINE_MOVE","WATER_MOVE") else 0)
def render_v2(games,model_map,title,target,mode):
    g=sorted(games,key=lambda x:(-signal(x),str(x.get("display_clock") or ""),str(x.get("game_id"))))
    css="font-family:-apple-system,BlinkMacSystemFont,Arial,sans-serif;font-size:14px;color:#1d3045;max-width:540px;margin:0 auto;line-height:1.55;"
    out=["<div style='"+css+"'><div style='padding:12px;background:#edf3f9;border-radius:10px;'>"
         "<div style='font-size:19px;font-weight:750;'>"+text(title)+"</div>"
         "<div style='color:#617389;font-size:12px;'>北京时间 "+text(target)+" · "+
         str(len(g))+" 场 · 按盘口变化排序</div></div>"]
    out.append("<div style='font-size:15px;font-weight:700;margin:14px 0 6px;'>比赛速览</div>")
    for i,x in enumerate(g,1):
        pred=model_map.get(str(x.get("game_id")),{})
        status=confidence(pred,x)
        out.append("<div style='padding:7px 0;border-bottom:1px solid #e8edf2;font-size:12px;'>"
                   "<b>#"+str(i).zfill(2)+"　"+text(x.get("display_clock"))+"　"+text(x.get("home_team"))+
                   " / "+text(x.get("away_team"))+"</b><div style='color:#657589;margin-top:2px;'>"+
                   text(status)+" · "+text(x.get("status") or "未建立历史波动")+"</div></div>")
    out.append("<div style='font-size:15px;font-weight:700;margin:15px 0 8px;'>逐场盘口与模型分析</div>")
    for i,x in enumerate(g,1):
        markets=x.get("markets") or {}
        spread=markets.get("full_spread") or {}
        total=markets.get("full_total") or {}
        pred=model_map.get(str(x.get("game_id")))
        status=x.get("status","FIRST_SNAPSHOT")
        body="<div style='font-size:12px;color:#68788e;'>#"+str(i).zfill(2)+" · "+text(x.get("display_clock"))+" · "+text(status)+"</div>"
        body+="<div style='font-size:16px;font-weight:700;margin:3px 0 8px;'>"+text(x.get("home_team"))+" VS "+text(x.get("away_team"))+"</div>"
        body+=score_prediction(pred)
        body+=market_change(spread,"full_spread")+market_change(total,"full_total")
        body+=compare(pred,spread,total)
        body+=para("<b>观察：</b>"+("首次抓取，仅建立基线；尚无小时涨跌。" if status=="FIRST_SNAPSHOT" else
                                  "存在盘口变化，需结合历史样本和独立模型复核。" if status in ("LINE_MOVE","WATER_MOVE","LINE_AND_WATER_MOVE") else
                                  "相比上次采样无明显异常变化。"))
        body+=para("<b>判断：</b>"+confidence(pred,x)+" · NO_BET")
        out.append(cell(body))
    out.append("<div style='font-size:11px;color:#68788e;padding:12px 3px;'>"
               "盘口采样时间≠博彩公司报价时间；让分方向与水位槽位尚未独立核验。"
               "模型均值和盘口的距离不等于投注价值；未通过完整盘口方向及价格验证前统一 NO_BET。"
               "</div></div>")
    return "".join(out)
def from_three(joined,model,movement):
    rows=[]
    byid={str(x.get("game_id")):x for x in movement.get("games",[])}
    for g in joined.get("nba_cba_games",[]):
        markets={}
        prior=byid.get(str(g.get("game_id")),{})
        for k in ("full_spread","full_total"):
            m=(g.get("markets") or {}).get(k) or {}
            d=(prior.get("changes") or {}).get("spread" if k=="full_spread" else "total") or {}
            markets[k]={"opening":m.get("opening"),"current":m.get("current"),
                        "previous":{"line":d.get("previous")},"delta_line_previous":d.get("delta")}
        rows.append({**g,"status":prior.get("status","FIRST_SNAPSHOT"),"markets":markets})
    return rows
def self_test():
    q={"game_id":"1","home_team":"甲","away_team":"乙","display_clock":"07:00",
       "status":"LINE_MOVE","markets":{
       "full_spread":{"opening":{"line":-3.5},"previous":{"line":-4.0},"current":{"line":-5.0},"delta_line_previous":-1},
       "full_total":{"opening":{"line":220},"previous":{"line":221},"current":{"line":223},"delta_line_previous":2}}}
    m={"1":{"model_status":"OK","model_probability":{"home":.62},"total_mean":224,"margin_mean_home_minus_away":5,
            "data_quality":{"quality":"PASS"}}}
    html=render_v2([q],m,"模拟","2026-10-31","hourly")
    assert "114.5" in html and "109.5" in html and "223.0" in html
    assert "方向未核验" in html and "NO_BET" in html
    assert "<table" not in html
    assert "比赛速览" in html and "模型总分与盘口差" in html
    print("PUSHPLUS_V2_COMPACT_SELF_TEST_PASS")
