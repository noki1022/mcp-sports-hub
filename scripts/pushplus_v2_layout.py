#!/usr/bin/env python3
"""PushPlus V2: compact iPhone game cards + historically grounded market movement.

The current Titan007 spread orientation, bookmaker timestamps, and quote provenance
have not been independently verified; NEVER convert raw first-side water into
home/away probability or quote a home-spread model advantage from an unverified
market. Model point-estimate vs total line is a numeric difference, NOT EV.

Renders only values present in real JSON inputs, no invented scores or advice.
"""
from __future__ import annotations

from datetime import datetime
from html import escape
import math
from zoneinfo import ZoneInfo

MAX_ITEMS=16
PADDING="padding:9px 11px;"
FONT="font-family:-apple-system,BlinkMacSystemFont,Arial,sans-serif;font-size:13px;line-height:1.52;color:#203149;"

def esc(v):
    return escape("—" if v is None or v=="" else str(v), quote=True)

def num(v):
    try:
        if v is None or v=="" or isinstance(v,bool):return None
        f=float(v)
        return f if math.isfinite(f) and -10000 < f < 10000 else None
    except (ValueError,TypeError):return None

def f(v, signed=False, digits=1):
    n=num(v)
    return "—" if n is None else (f"{n:+.{digits}f}" if signed else f"{n:.{digits}f}")

def prob(v):
    p=num(v)
    return f"{p*100:.1f}%" if p is not None and 0<=p<=1 else "—"

def changes(v):
    x=num(v)
    if x is None:return "暂无"
    if abs(x)<.0001:return "持平"
    return ("升" if x>0 else "降")+f(abs(x))

def item_model(model):
    if not isinstance(model,dict):return None
    if model.get("model_status") not in ("OK","PARTIAL"):return None
    return model

def quality(model):
    if model is None:return "模型不可用"
    q=model.get("data_quality") or {}
    return "样本充足" if q.get("quality")=="PASS" else "样本待核"

def delta_value(current,old):
    a,b=num(current),num(old)
    return round(a-b,5) if a is not None and b is not None else None

def market_status(d):
    return str(d.get("status") or "")

def priority(game,model):
    status=market_status(game)
    q=quality(item_model(model))
    if q=="模型不可用":return (2,"数据待核")
    if status in ("LINE_MOVE","WATER_MOVE","LINE_AND_WATER_MOVE","ABRUPT_MOVE","SIGNIFICANT_MARKET_MOVE"):
        return (0 if q=="样本充足" else 1,"波动关注" if q=="样本充足" else "谨慎观察")
    return (1,"常规跟踪" if q=="样本充足" else "谨慎观察")

def strip(title,description):
    return ("<div style='background:#eef3fa;border-radius:9px;padding:11px 12px;margin-bottom:8px;'>"
            "<div style='font-size:18px;font-weight:750;color:#182d48;'>"+esc(title)+"</div>"
            "<div style='font-size:12px;color:#607086;margin-top:3px;'>"+esc(description)+"</div></div>")

def paragraph(label,value,small=False):
    return ("<div style='margin:5px 0;font-size:"+("12" if small else "13")+"px;line-height:1.55;'>"
            "<span style='color:#63748a;'>"+esc(label)+"</span> "+value+"</div>")

def line(name,opening,previous,current,first=None,water_delta=None):
    now,old,origin=num(current),num(previous),num(opening)
    direct=f(current)
    base=f(opening)
    prev=f(previous)
    prior_delta=delta_value(now,old)
    open_delta=delta_value(now,origin)
    text="<b>"+esc(name)+"</b> "+esc(base)+" → <strong>"+esc(direct)+"</strong>"
    if prior_delta is not None:
        text+="<span style='color:#526b86;'> · 较上次 "+esc(f(prior_delta,True))+"</span>"
    else:
        text+="<span style='color:#73839a;'> · 无前次快照</span>"
    extra=[]
    if open_delta is not None:extra.append("较开盘 "+f(open_delta,True))
    first_delta=delta_value(now,first)
    if first_delta is not None:extra.append("较首采样 "+f(first_delta,True))
    if water_delta is not None:extra.append("原始槽位1去水变化 "+f(100*water_delta,True)+"百分点")
    return paragraph("",text)+(
        "<div style='margin:0 0 5px 5px;color:#63748a;font-size:11px;'>"+esc(" · ".join(extra))+"</div>"
        if extra else "")

def model_box(model,total_line=None,spread_line=None,orientation_verified=False):
    v=item_model(model)
    if not v:
        return ("<div style='padding:8px 9px;background:#f2f5f9;border-radius:7px;color:#536781;'>"
                "<b>独立模型</b> · 缺少可核验预测，暂不判断方向</div>")
    m=num(v.get("margin_mean_home_minus_away"))
    total=num(v.get("total_mean"))
    if m is not None and total is not None:
        # These are implied continuous scoring means, NOT a correct-score pick.
        score=f((total+m)/2,False,0)+" : "+f((total-m)/2,False,0)
    else:score="—"
    p=v.get("model_probability") or {}
    main=("<div style='padding:8px 9px;background:#f1f5fa;border-radius:7px;'>"
          "<div style='font-size:11px;color:#5b6e86;'>独立模型 · "+esc(quality(v))+"</div>"
          "<div style='font-size:18px;font-weight:750;'>"+esc(score)+
          " <span style='font-size:11px;font-weight:400;'>推算得分均值（非精确比分）</span></div>"
          "<div style='font-size:12px;'>主胜 "+esc(prob(p.get("home")))+"　"
          "客胜 "+esc(prob(p.get("away")))+"　"
          "净胜 "+esc(f(m,True))+"　总分 "+esc(f(total))+"</div></div>")
    gap=delta_value(total,total_line)
    main+=paragraph("总分模型−即时盘", "<b>"+esc(f(gap,True))+"</b> 分" if gap is not None else "—（数据不足）", True)
    spread_gap=delta_value(m,spread_line) if orientation_verified else None
    if spread_gap is None:
        main+=paragraph("让分模型差", "—（原始盘口主客方向未核验）", True)
    else:
        main+=paragraph("让分模型差", "<b>"+esc(f(spread_gap,True))+"</b> 分（方向已核验）", True)
    return main

def interpretation(game,model,opening_spread=None,opening_total=None,current_spread=None,current_total=None,
                   prior_spread=None,prior_total=None):
    v=item_model(model)
    if v is None:return "独立模型缺失，本场只展示可核实的盘口记录；不做方向判断。"
    words=[]
    dt=delta_value(current_total,prior_total)
    if dt is not None and abs(dt)>.0001:
        words.append("总分较上次"+("上调" if dt>0 else "下调")+f(abs(dt))+"分")
    ds=delta_value(current_spread,prior_spread)
    if ds is not None and abs(ds)>.0001:
        words.append("让分原始盘口数值变动"+f(ds,True)+"分")
    if not words:
        if market_status(game) in ("FIRST_SNAPSHOT","BASELINE"):
            words.append("首次采样，暂无可核实的上一时段变化")
        else:words.append("无明显可确认的上次盘口变化")
    gap=delta_value(v.get("total_mean"),current_total)
    if gap is not None:
        words.append("模型总分与现盘差"+f(gap,True)+"分")
    return "；".join(words)+"。数值差不是投注优势；市场方向未核验，暂不判断是否值得下注。"

def overview(records):
    heading=("<div style='padding:6px 2px 5px;font-size:14px;font-weight:750;'>"
             "八场速览 / 重点观察</div>")
    pieces=[heading]
    for i,(g,model,label) in enumerate(records[:MAX_ITEMS],1):
        name=esc(g.get("home_team"))+" / "+esc(g.get("away_team"))
        p=((item_model(model) or {}).get("model_probability") or {}).get("home")
        a=(esc(f"#{i:02d}")+"　"+esc(g.get("display_clock"))+"　"+name)
        b=("主胜 "+esc(prob(p))+"　"+esc(label)+"　"+esc(quality(item_model(model))))
        pieces.append("<div style='border-bottom:1px solid #e5ebf2;padding:6px 2px;'>"
                      "<div style='font-size:13px;font-weight:650;'>"+a+"</div>"
                      "<div style='color:#61758f;font-size:11px;margin-top:2px;'>"+b+"</div></div>")
    return "".join(pieces)

def card(i,g,model,label,markets,has_hourly):
    head=("<div style='font-size:12px;color:#63758d;'>#"+f"{i:02d}"+" · "+
          esc(g.get("display_clock"))+" · "+esc(g.get("league","NBA/CBA"))+
          " · "+esc(label)+"</div>")
    head+=("<div style='font-size:15px;font-weight:750;margin:3px 0 7px;'>"
           +esc(g.get("home_team"))+" vs "+esc(g.get("away_team"))+"</div>")
    sp=markets.get("full_spread") or {};tot=markets.get("full_total") or {}
    body=model_box(model,(tot.get("current") or {}).get("line"),(sp.get("current") or {}).get("line"))
    for record,title in ((sp,"让分原始盘"),(tot,"总分")):
        op=(record.get("opening") or {}).get("line")
        previous=(record.get("previous") or {}).get("line")
        now=(record.get("current") or {}).get("line")
        first=(record.get("first_snapshot") or {}).get("line")
        water=record.get("delta_devig_raw_slot1") if has_hourly else None
        body+=line(title,op,previous,now,first,water)
    desc=interpretation(g,model,
      (sp.get("opening") or {}).get("line"),(tot.get("opening") or {}).get("line"),
      (sp.get("current") or {}).get("line"),(tot.get("current") or {}).get("line"),
      (sp.get("previous") or {}).get("line"),(tot.get("previous") or {}).get("line"))
    body+=("<div style='font-size:12px;color:#374f69;line-height:1.55;margin-top:6px;'>"
           "<b>模型×盘口：</b>"+esc(desc)+"</div>")
    body+=("<div style='border-top:1px solid #ecf0f5;margin-top:8px;padding-top:6px;"
           "font-size:11px;color:#76859a;'>数据状态："+esc(quality(item_model(model)))+
           " · 盘口主客方向未核验 · NO_BET</div>")
    return ("<div style='border:1px solid #e3eaf2;border-radius:10px;margin:10px 0;"
            "padding:10px 11px;background:#fff;'>"+head+body+"</div>")

def common_end():
    return ("<div style='color:#65758a;font-size:11px;margin:11px 1px;line-height:1.6;'>"
            "盘口源采样时间≠博彩公司真实报价时间。比分仅为模型得分均值换算，"
            "不是精确比分预测。模型-盘口差值不等于正期望收益。"
            "未取得合法、明确的主客方向和报价证据前统一 NO_BET。</div>")

def make(records,target,label,summary,has_hourly):
    ordered=sorted(records,key=lambda x:(priority(x[0],x[1])[0],str(x[0].get("display_clock") or ""),
                                      str(x[0].get("game_id") or "")))
    scored=[(g,m,priority(g,m)[1]) for g,m,markets in ordered]
    head=strip(label,"北京时间 "+esc(target)+" · "+esc(summary)+" · 盘口+独立模型")
    body=overview(scored)
    body+="<div style='margin:13px 0 5px;font-size:14px;font-weight:750;'>逐场解析</div>"
    for i,(g,m,mk) in enumerate(ordered[:MAX_ITEMS],1):
        body+=card(i,g,m,priority(g,m)[1],mk,has_hourly)
    return ("<div style='"+FONT+"max-width:520px;margin:0 auto;'>"+
            head+body+common_end()+"</div>")

def daily_report(joined,model,movement):
    allgames=joined.get("nba_cba_games",[])
    moving={str(g.get("game_id")):g for g in movement.get("games",[])}
    preds={str(g.get("game_id")):g for g in model.get("games",[])}
    rows=[]
    for g in allgames[:MAX_ITEMS]:
        mk={}
        mo=moving.get(str(g.get("game_id")),{})
        for k,short in (("full_spread","spread"),("full_total","total")):
            raw=(g.get("markets") or {}).get(k) or {}
            pc=((mo.get("changes") or {}).get(short) or {})
            current=raw.get("current") or {}
            mk[k]={"opening":raw.get("opening") or {},
                   "previous":{"line":pc.get("previous")} if pc.get("previous") is not None else None,
                   "current":current}
        entry={**g,"status":mo.get("status","BASELINE")}
        rows.append((entry,preds.get(str(g.get("game_id"))),mk))
    target=joined.get("requested_display_date","未知日期")
    return "NBA/CBA 模型速报｜"+str(target),make(rows,target,"NBA / CBA 赛前研判 V2",str(len(allgames))+" 场",False),len(rows)

def hourly_report(movement,model,final_window):
    preds={str(g.get("game_id")):g for g in model.get("games",[])}
    final_ids={str(g.get("game_id")) for g in final_window.get("nba_cba_games",[])}
    flagged={"LINE_MOVE","WATER_MOVE","LINE_AND_WATER_MOVE"}
    rows=[]
    for g in movement.get("games",[]):
        if g.get("status") in flagged or str(g.get("game_id")) in final_ids:
            rows.append(({**g,"league":g.get("league"),"status":g.get("status")},
                         preds.get(str(g.get("game_id"))),g.get("markets") or {}))
    target=movement.get("target_date","未知日期")
    return "NBA/CBA 盘口波动 V2｜"+str(target),make(rows,target,"NBA / CBA 盘口动态 V2",str(len(rows))+" 场关注",True),len(rows)

def selftest():
    joined={"requested_display_date":"2026-11-01","nba_cba_games":[{
        "game_id":"1","display_clock":"08:00","league":"NBA","home_team":"甲队<script>",
        "away_team":"乙队","markets":{"full_spread":{"opening":{"line":-3.5},"current":{"line":-4.5}},
                              "full_total":{"opening":{"line":220},"current":{"line":224}}}}]}
    mod={"games":[{"game_id":"1","model_status":"OK",
                   "model_probability":{"home":.62,"away":.38},"margin_mean_home_minus_away":6,
                   "total_mean":222,"data_quality":{"quality":"PASS"}}]}
    movement={"target_date":"2026-11-01","games":[{
      "game_id":"1","home_team":"甲队<script>","away_team":"乙队","league":"NBA",
      "display_clock":"08:00","status":"LINE_MOVE",
      "markets":{"full_spread":{"opening":{"line":-3.5},"previous":{"line":-4},
                                  "current":{"line":-4.5},"first_snapshot":{"line":-3.5}},
                 "full_total":{"opening":{"line":220},"previous":{"line":222},
                               "current":{"line":224},"first_snapshot":{"line":221}}}}]}
    a,b,c=daily_report(joined,mod,{})
    assert c==1 and "模型-盘口差值" in b and "—（原始盘口主客方向未核验）" in b
    assert "&lt;script&gt;" in b and "<script>" not in b
    assert "111 : 105" in b and "主胜 62.0%" in b
    assert "总分模型−即时盘" in b and "-2.0" in b
    title,html,n=hourly_report(movement,mod,{"nba_cba_games":[]})
    assert n==1 and "较上次 +2.0" in html and "较首采样 +3.0" in html
    assert "NO_BET" in html
    _,first,_=daily_report(joined,{},{"games":[]})
    assert "模型不可用" in first and "无前次快照" in first
    print("PUSHPLUS_V2_COMPACT_MODEL_MOVEMENT_SELF_TEST_PASS")

if __name__=="__main__":selftest()
