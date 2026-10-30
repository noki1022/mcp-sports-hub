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

STATUS_CN={
    "LINE_MOVE":"让分或总分变动",
    "WATER_MOVE":"水位变化",
    "LINE_AND_WATER_MOVE":"盘口与水位均变",
    "FIRST_SNAPSHOT":"首次采样",
    "STABLE_OR_MINOR_MOVE":"变化较小",
    "BASELINE":"基线记录",
    "ABRUPT_MOVE":"异常波动",
    "SIGNIFICANT_MARKET_MOVE":"显著波动"
}
def status_label(status):
    return STATUS_CN.get(str(status),"状态待核验")
def cell(body):
    return "<div style='padding:10px 11px;margin:9px 0;border:1px solid #e2e9f1;border-radius:10px;'>"+body+"</div>"
def para(body):
    return "<div style='font-size:13px;line-height:1.6;margin:5px 0;color:#26384e;'>"+body+"</div>"

def market_change(m,kind):
    q=m.get("current") or {}
    opening=m.get("opening") or {}
    previous=m.get("previous") or {}
    first=m.get("first_snapshot") or {}
    label="让分原始数值" if kind=="full_spread" else "全场总分"
    current=num(q.get("line"))
    prior=num(previous.get("line"))
    op=num(opening.get("line"))
    base=num(first.get("line"))
    current_display=f(current)
    head=("<div style='padding:6px 0;border-bottom:1px solid #f1f4f8;'>"
          "<div style='font-size:13px;'><b>"+label+"</b>　"+
          "初 "+f(op)+" → <b>现 "+current_display+"</b></div>")
    if current is None:
        return head+"<div style='font-size:11px;color:#7a8999;'>当前未取得可靠盘口数值</div></div>"
    recent=current-prior if prior is not None else None
    cumulative=current-base if base is not None else None
    last_info=("上次 "+f(prior)+"｜变化 "+f(recent,True)) if recent is not None else "无上一小时可比数据"
    accumulated=("｜首采累计 "+f(cumulative,True)) if cumulative is not None else ""
    return (head+"<div style='font-size:11px;color:#64758a;line-height:1.5;margin-top:3px;'>"+
            last_info+accumulated+"</div></div>")

def score_prediction(pred):
    if not pred or pred.get("model_status") not in ("OK","PARTIAL"):
        return "<div style='background:#f2f5f9;border-radius:7px;padding:9px 10px;font-size:12px;'>独立模型：缺失或不可用，不生成预测比分</div>"
    total=num(pred.get("total_mean"))
    margin=num(pred.get("margin_mean_home_minus_away"))
    if total is None or margin is None or (total+margin)<0 or (total-margin)<0:
        return "<div style='background:#f2f5f9;border-radius:7px;padding:9px 10px;font-size:12px;'>独立模型：均值无效，无法换算得分</div>"
    hp=(total+margin)/2
    ap=(total-margin)/2
    p=(pred.get("model_probability") or {}).get("home")
    prob="—" if num(p) is None or not 0<=num(p)<=1 else f"{num(p)*100:.1f}%"
    return ("<div style='background:#eef3f9;border-radius:8px;padding:9px 10px;margin:8px 0 5px;'>"
            "<div style='font-size:11px;color:#61738a;'>模型预测 · 得分均值（非精确比分）</div>"
            "<div style='font-size:18px;font-weight:750;margin:2px 0;'>"+f(hp)+" : "+f(ap)+
            "<span style='font-size:12px;font-weight:500;color:#415875;'>　主胜 "+prob+"</span></div>"
            "<div style='font-size:12px;color:#415875;'>净胜 "+f(margin,True)+
            "　｜　预测总分 "+f(total)+"</div></div>")

def compare(pred, spread, total):
    if not pred or pred.get("model_status") not in ("OK","PARTIAL"):
        return para("<b>模型与盘口：</b>尚无可核实的模型差值")
    margin=num(pred.get("margin_mean_home_minus_away"))
    t=num(pred.get("total_mean"))
    curr_spread=num((spread.get("current") or {}).get("line"))
    curr_total=num((total.get("current") or {}).get("line"))
    # No directional spread edge or implied coverage probability before verifying side semantics.
    gap=(t-curr_total) if t is not None and curr_total is not None else None
    total_text="<b>"+f(gap,True)+" 分</b>" if gap is not None else "—"
    return ("<div style='background:#f8fafc;border-left:3px solid #a1b4cc;padding:7px 9px;"
            "margin:8px 0 5px;font-size:12px;line-height:1.55;'>"
            "<b>模型 vs 盘口</b>　总分差 "+total_text+
            "<div style='color:#5d7188;'>让分差 —（主客方向待核实）</div></div>")

def confidence(pred,move):
    if not pred or pred.get("model_status") not in ("OK","PARTIAL"):
        return "模型不可用"
    q=pred.get("data_quality") or {}
    qual=q.get("quality") if isinstance(q,dict) else None
    if qual not in ("PASS","GOOD"):return "模型质量待核"
    if pred.get("model_status")=="PARTIAL":return "模型部分数据"
    return "模型数据已验收"
def signal(g):
    moves=g.get("markets") or {}
    n=sum(abs(num((moves.get(k) or {}).get("delta_line_previous")) or 0) for k in ("full_spread","full_total"))
    return n+(2 if g.get("status") in ("LINE_AND_WATER_MOVE","LINE_MOVE","WATER_MOVE") else 0)

def render_v2(games,model_map,title,target,mode):
    g=sorted(games,key=lambda x:(-signal(x),str(x.get("display_clock") or ""),str(x.get("game_id"))))
    css="font-family:-apple-system,BlinkMacSystemFont,Arial,sans-serif;font-size:14px;color:#1d3045;max-width:540px;margin:0 auto;line-height:1.52;"
    synthetic="模拟" in str(title)
    heading=("模拟报告 · 8场速览" if synthetic else
             "盘口异动 · 重点速览" if mode=="hourly" else "赛前模型 · 比赛速览")
    sub=("以下全部为虚构数据，仅测试排版" if synthetic else
         "北京时间 "+str(target)+" · "+str(len(g))+" 场 · 变化优先（非投注排名）")
    out=["<div style='"+css+"'><div style='padding:10px 12px;background:#eef3fa;border-radius:9px;'>"
         "<div style='font-size:17px;font-weight:750;'>"+text(heading)+"</div>"
         "<div style='color:#617389;font-size:12px;margin-top:3px;'>"+text(sub)+"</div></div>"]
    out.append("<div style='font-size:14px;font-weight:700;margin:13px 0 5px;'>八场核心数据</div>" if synthetic else "<div style='font-size:14px;font-weight:700;margin:13px 0 5px;'>比赛速览</div>")
    for i,x in enumerate(g,1):
        pred=model_map.get(str(x.get("game_id")),{})
        total=num((pred or {}).get("total_mean"))
        win=num(((pred or {}).get("model_probability") or {}).get("home"))
        status=status_label(x.get("status"))
        mk=(x.get("markets") or {}).get("full_total") or {}
        q=num((mk.get("current") or {}).get("line"))
        gap=(total-q) if total is not None and q is not None else None
        home=text(x.get("home_team"));away=text(x.get("away_team"))
        out.append("<div style='padding:7px 2px;border-bottom:1px solid #e8edf2;'>"
                   "<div style='font-size:13px;font-weight:650;'>#"+str(i).zfill(2)+"　"+
                   text(x.get("display_clock"))+"　客队："+away+"　｜　主队："+home+"</div>"
                   "<div style='font-size:11px;color:#61758a;margin-top:2px;'>"
                   "主胜 "+(f(win*100)+"%" if win is not None and 0<=win<=1 else "—")+
                   "　· 模总 "+f(total)+"　· 现盘 "+f(q)+
                   "　· 差 "+f(gap,True)+"</div><div style='font-size:11px;color:#718297;'>"+text(status)+"</div></div>")
    out.append("<div style='font-size:14px;font-weight:700;margin:14px 0 7px;'>逐场模型与盘口</div>")
    for i,x in enumerate(g,1):
        markets=x.get("markets") or {}
        spread=markets.get("full_spread") or {}
        total=markets.get("full_total") or {}
        pred=model_map.get(str(x.get("game_id")))
        status=x.get("status","FIRST_SNAPSHOT")
        body="<div style='font-size:11px;color:#68788e;'>#"+str(i).zfill(2)+" · "+text(x.get("display_clock"))+" · "+text(status_label(status))+"</div>"
        body+="<div style='font-size:15px;font-weight:750;margin:4px 0 7px;'>"+"客队："+text(x.get("away_team"))+"　｜　主队："+text(x.get("home_team"))+"</div>"
        body+=score_prediction(pred)
        body+=market_change(spread,"full_spread")+market_change(total,"full_total")
        body+=compare(pred,spread,total)
        if status=="FIRST_SNAPSHOT":
            summary="首次采样，仅建立基线，暂不能计算小时涨跌。"
        elif status in ("LINE_MOVE","WATER_MOVE","LINE_AND_WATER_MOVE"):
            sp=(spread.get("delta_line_previous") if spread else None)
            tp=(total.get("delta_line_previous") if total else None)
            if num(sp) is not None or num(tp) is not None:
                summary="较上次采样：让分 "+f(sp,True)+"，总分 "+f(tp,True)+"；变化幅度不代表投注价值。"
            else:
                summary="检测到盘口变化，但缺乏完整的逐小时数值证据。"
        else:
            summary="盘口相对上一采样暂无明确异常。"
        review=x.get("dynamic_review") or {}
        if review:
            body+=("<div style='background:#f1f5f9;border-radius:7px;padding:8px;font-size:12px;line-height:1.6;'>"+
                   "<b>本小时动态研判</b><div>让分："+text(review.get("spread_observation","—"))+
                   "</div><div>总分："+text(review.get("total_observation","—"))+
                   "</div><div>模型与总分盘差："+text(review.get("total_model_market_gap","—"))+
                   "；结论：仅观察，未核验方向，不改写独立概率。</div></div>")
        body+=("<div style='font-size:12px;line-height:1.55;margin-top:6px;'>"
               "<b>观察：</b>"+summary+"</div>")
        body+=("<div style='border-top:1px solid #e8edf2;margin-top:8px;padding-top:6px;"
               "font-size:11px;color:#61748a;'>"+text("纯模拟·未经真实验收" if synthetic else confidence(pred,x))+
               " · 方向待核 · <b>暂不参与</b></div>")
        out.append(cell(body))
    out.append("<div style='font-size:11px;color:#68788e;padding:12px 3px;'>"
               "统一说明：盘口采样时间不等于博彩公司报价时间，主客方向与水位槽位尚未核验。"
               "模型得分为均值估算，不代表精确比分；模型与盘口的差值不等于投注优势。"
               "未完成方向和价格核验前统一 NO_BET。</div></div>")
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
    assert "LINE_MOVE" not in html and "让分或总分变动" in html
    assert "主胜 62.0%" in html and "模总 224.0" in html
    assert "客队：乙" in html and "主队：甲" in html
    assert "方向待核" in html and "NO_BET" in html
    assert "<table" not in html
    assert "八场核心数据" in html and "模型 vs 盘口" in html
    assert "纯模拟·未经真实验收" in html and "模型数据已验收" not in html
    print("PUSHPLUS_V2_COMPACT_SELF_TEST_PASS")
