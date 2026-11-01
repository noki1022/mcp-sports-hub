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
    label="机构让分（原始盘）" if kind=="full_spread" else "机构全场总分"
    current=num(q.get("line"))
    prior=num(previous.get("line"))
    op=num(opening.get("line"))
    base=num(first.get("line"))
    current_display=f(current,kind=="full_spread")
    head=("<div style='padding:6px 0;border-bottom:1px solid #f1f4f8;'>"
          "<div style='font-size:13px;'><b>"+label+"</b>　"+
          "初 "+f(op,kind=="full_spread")+" → <b>现 "+current_display+"</b></div>")
    if current is None:
        return head+"<div style='font-size:11px;color:#7a8999;'>当前未取得可靠盘口数值</div></div>"
    recent=current-prior if prior is not None else None
    cumulative=current-base if base is not None else None
    last_info=("上次 "+f(prior,kind=="full_spread")+"｜变化 "+f(recent,True)) if recent is not None else "无上一小时可比数据"
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
            "<div style='font-size:18px;font-weight:750;margin:2px 0;'>"+"主队 "+f(hp)+"　｜　客队 "+f(ap)+
            "<span style='font-size:12px;font-weight:500;color:#415875;'>　主胜 "+prob+"</span></div>"
            "<div style='font-size:12px;color:#415875;'>净胜 "+f(margin,True)+
            "　｜　预测总分 "+f(total)+"</div></div>")

def probability_disagreement(pred, game):
    """Explicit market/model anomaly; no automatic odds-based model overwrite."""
    if not pred or pred.get("model_status") not in ("OK","PARTIAL"):
        return ""
    p=num((pred.get("model_probability") or {}).get("home"))
    raw=num((pred.get("model_probability_raw") or {}).get("home"))
    odds=((game.get("jc_007_price_shadow") or {}).get("markets") or {}).get("win_lose") or {}
    current=(odds.get("data") or {}).get("current") or {}
    home_price=num(current.get("first_side"))
    away_price=num(current.get("second_side"))
    if odds.get("status")!="OBSERVED" or home_price is None or away_price is None or home_price<=1 or away_price<=1 or p is None:
        return ""
    implied_home=(1/home_price)/((1/home_price)+(1/away_price))
    gap=abs(implied_home-p)
    calibration_gap=abs(raw-p) if raw is not None else None
    if gap<0.20 and (calibration_gap is None or calibration_gap<0.15):
        return ""
    raw_text=(f(raw*100)+"%" if raw is not None else "未提供")
    return ("<div style='padding:9px;margin:7px 0;background:#fff1e4;"
      "border-left:3px solid #cf721a;border-radius:5px;color:#764014;font-size:12px;'>"
      "<b>主胜概率异常 · 暂不采信极端胜率</b>"
      "<div>007 竞彩去水约 "+f(implied_home*100)+"%　｜　模型原始 "+raw_text+
      "　｜　校准后 "+f(p*100)+"%</div>"
      "<div>校准后与市场相差 "+f(gap*100)+" 个百分点。需检查历史样本、校准尾部、伤停和盘口时效；"
      "市场概率不是比赛真实概率，禁止直接按此差距认定价值。</div></div>")

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

def verdict_summary(v):
    """Show 007 institutional research using the *actual* signed home handicap.

    Institutional raw +5.5 means the home team gives 5.5; display home -5.5.
    Do not present raw 5.5 as an ambiguous or positive home handicap.
    """
    if not v:
        return "<div style='font-size:11px;color:#98520b;'>007机构研判：暂无可靠预测</div>"
    markets=v.get("markets") or {}
    sp=markets.get("SPREAD") or {}
    tot=markets.get("TOTAL") or {}
    raw=num(sp.get("line"))
    signed=num(sp.get("signed_home_handicap"))
    if signed is None and raw is not None:
        # Legacy snapshots may lack the new field; the source raw line is
        # institutional + = home gives. Explicitly convert rather than guessing.
        signed=-raw
    direction=sp.get("direction")
    legacy_rule=sp.get("rule")=="PROVISIONAL_HOME_HANDICAP_ADD_TO_HOME_MINUS_AWAY"
    if legacy_rule:
        direction=None  # Prior snapshots used the inverted formula; do not silently publish.
    if signed is not None and direction in ("HOME","AWAY"):
        handicap=("主队让 "+f(-signed)+" 分" if signed<0 else
                  "主队受让 "+f(signed)+" 分" if signed>0 else "平手")
        target="主队赢盘" if direction=="HOME" else "客队赢盘"
        sp_label=handicap+"（主队盘口 "+f(signed,True)+"）→ 倾向"+target
    else:
        sp_label="旧版方向失效，待按正确让分符号重新计算" if legacy_rule else "数据不足，暂不判断"
    total_line=num(tot.get("line"))
    td=tot.get("direction")
    tl=("倾向"+("大分" if td=="OVER" else "小分")+"（"+f(total_line)+"）"
        if total_line is not None and td in ("OVER","UNDER") else "数据不足，暂不判断")
    return ("<div style='font-size:11px;line-height:1.65;color:#264564;'>"
        "<b>007机构盘口研究</b><div>让分："+text(sp_label)+
        "</div><div>总分："+text(tl)+
        "</div><div style='color:#718297;'>研究倾向，不等于已验证投注优势</div></div>")

def jingcai_status(x, detailed=False):
    """007 lottery sides: left=home and right=away, never anonymous slot labels.

    Website confirmed: first odds are home, second away; positive handicap
    gives points to HOME (away gives), negative handicap home gives points.
    Total first=OVER, second=UNDER. Institution odds are rendered separately.
    """
    if not detailed:
        return ""  # Summary contains match + model; no duplicate orange odds notice.
    observed=((x.get("jc_007_price_shadow") or {}).get("markets") or {})
    if not observed:
        return ""
    home=text(x.get("home_team"))
    away=text(x.get("away_team"))
    odd=lambda v: ("—" if num(v) is None else "{:.2f}".format(num(v)))
    lines=[]
    for key,title in (("win_lose","胜负"),("handicap","让分胜负"),("total","大小分")):
        entry=observed.get(key) or {}
        state=entry.get("status")
        if state=="NOT_ON_SALE_USER_CONFIRMED":
            lines.append("<div><b>"+title+"</b>　未开售（用户确认）</div>")
            continue
        if state!="OBSERVED":
            lines.append("<div><b>"+title+"</b>　暂无竞彩报价</div>")
            continue
        data=entry.get("data") or {}
        current=data.get("current") or {}
        opening=data.get("opening") or {}
        first=odd(current.get("first_side"))
        second=odd(current.get("second_side"))
        if key=="win_lose":
            lines.append("<div><b>胜负</b>　主胜（"+home+"）<b>"+first+
                         "</b>　｜　客胜（"+away+"）<b>"+second+"</b></div>")
        elif key=="handicap":
            line=num(current.get("line"))
            if line is None:
                lines.append("<div><b>让分胜负</b>　盘口缺失，方向不展示</div>")
                continue
            # Official lottery sign convention: + means away gives, home receives.
            home_word="受让" if line>0 else "让分" if line<0 else "平手"
            away_word="让分" if line>0 else "受让" if line<0 else "平手"
            sign_home=f(line,True)
            sign_away=f(-line,True)
            opening_line=num(opening.get("line"))
            movement=("　<small>初盘 "+f(opening_line,True)+" → 现盘 "+sign_home+"</small>"
                      if opening_line is not None and opening_line!=line else "")
            lines.append("<div><b>让分胜负</b>"+movement+"</div>"+
                         "<div>主队 "+home+" <b>"+sign_home+"</b>（"+home_word+
                         "）· 让分主胜 <b>"+first+"</b></div>"+
                         "<div>客队 "+away+" <b>"+sign_away+"</b>（"+away_word+
                         "）· 让分客胜 <b>"+second+"</b></div>")
        else:
            line=num(current.get("line"))
            if line is None:
                lines.append("<div><b>大小分</b>　盘口缺失，方向不展示</div>")
                continue
            opening_line=num(opening.get("line"))
            movement=("　<small>初盘 "+f(opening_line)+" → 现盘 "+f(line)+"</small>"
                      if opening_line is not None and opening_line!=line else "")
            lines.append("<div><b>大小分</b>　总分线 <b>"+f(line)+"</b>"+movement+"</div>"+
                         "<div>大分 <b>"+first+"</b>　｜　小分 <b>"+second+"</b></div>")
    if not lines:return ""
    return ("<div style='font-size:12px;line-height:1.7;padding:9px 10px;"
            "margin:7px 0;background:#f5f7fa;border-radius:7px;color:#24364b;'>"
            "<div style='font-weight:700;margin-bottom:3px;'>竞彩赔率（007）· 主队在左，客队在右</div>"+
            "".join(lines)+"</div>")

def five_market_panel(x):
    """Exactly five clearly named research rows, source-specific and independently graded."""
    all_keys=(
       ("JINGCAI_WIN","① 竞彩胜负"),
       ("JINGCAI_HANDICAP","② 竞彩让分胜负"),
       ("JINGCAI_TOTAL","③ 竞彩大小分"),
       ("CROWN_HANDICAP","④ 皇冠让分"),
       ("CROWN_TOTAL","⑤ 皇冠大小分"))
    doc=x.get("five_market_forecast") or {}
    rows=doc.get("markets") or {}
    home=text(x.get("home_team"))
    away=text(x.get("away_team"))
    def side(market,val):
        if market=="JINGCAI_WIN":
            return "主胜 · "+home if val=="HOME_WIN" else "客胜 · "+away if val=="AWAY_WIN" else None
        if market.endswith("HANDICAP"):
            return "主队赢盘 · "+home if val=="HOME_COVER" else "客队赢盘 · "+away if val=="AWAY_COVER" else None
        return "大分" if val=="OVER" else "小分" if val=="UNDER" else None
    lines=[]
    for key,name in all_keys:
        obj=rows.get(key) or {}
        status=obj.get("status","MISSING_FIVE_MARKET_ARTIFACT")
        direction=side(key,obj.get("direction"))
        if status=="DIRECTION_ISSUED" and direction:
            mark=num(obj.get("signed_home_handicap")) if key.endswith("HANDICAP") else num(obj.get("line"))
            qualifier=("　主队盘口 "+f(mark,True) if key.endswith("HANDICAP") and mark is not None else
                       "　总分线 "+f(mark) if key.endswith("TOTAL") and mark is not None else "")
            conclusion="<b>"+text(direction)+"</b>"+qualifier
            probability=num(obj.get("model_direction_probability"))
            if probability is not None and 0<=probability<=1:
                conclusion+="　模型方向概率 "+f(probability*100)+"%"
            else:
                reason=text(obj.get("probability_status") or obj.get("model_probability_status") or "模型输入/σ不可用")
                conclusion+="　模型方向概率不可用（"+reason+"）"
            consensus=obj.get("market_consensus") or {}
            price_status=consensus.get("market_price_consensus_status")
            market_p=num(consensus.get("market_price_probability_for_model_direction"))
            gap=num(consensus.get("model_minus_market_probability_for_model_direction"))
            price_count=int(consensus.get("same_line_company_count") or 0)
            consensus_line=num(consensus.get("consensus_line"))
            if price_status=="AVAILABLE_SAME_LINE_MEDIAN" and market_p is not None:
                line_text=("，共识线 "+f(consensus_line) if consensus_line is not None else "")
                line_fit=("本玩法同线" if consensus.get("direct_line_matches_price_reference") is True
                          else "仅共识线参考")
                gap_text=("，模型-市场 "+f(gap*100,True)+"pp" if gap is not None else "")
                conclusion+=("<div style='font-size:11px;color:#52677f;'>多机构同线去水："+
                    str(price_count)+"家"+line_text+"，共识线模型方向市场概率 "+
                    f(market_p*100)+"%"+gap_text+"（"+line_fit+"；影子对照，不改写生产概率）</div>")
            elif price_status=="INSUFFICIENT_SAME_LINE_COMPANIES":
                conclusion+="<div style='font-size:11px;color:#718297;'>多机构同线价格共识不足3家，不计算市场概率</div>"
            elif key=="JINGCAI_WIN" and consensus.get("proxy_type")=="SPREAD_FAVORITE_NOT_MONEYLINE_ODDS":
                conclusion+="<div style='font-size:11px;color:#718297;'>多机构独赢赔率未采集；让分盘只作胜负方向参照</div>"
            if obj.get("quote_freshness")=="ARCHIVED_PRIOR_NOT_LIVE":
                conclusion+="（007 ID3历史赛前快照，非实时；采集于 "+text(obj.get("captured_at_utc"))+"）"
            if obj.get("strength")=="WEAK":conclusion+="（弱倾向）"
        elif status=="NOT_ON_SALE_USER_CONFIRMED":
            conclusion="未开售，不计入该玩法命中率"
        else:
            conclusion="数据不足，无法有效判断（"+text(status)+"）"
        lines.append("<div style='padding:4px 0;border-bottom:1px solid #e1e8f0;'>"+
                     "<b>"+name+"</b>　"+conclusion+"</div>")
    return ("<div style='font-size:12px;padding:9px 10px;margin:7px 0;"
            "background:#eff5fb;border-radius:8px;color:#22384f;line-height:1.65;'>"
            "<div style='font-size:13px;font-weight:750;'>五玩法独立研判 · 赛前锁定</div>"+
            "".join(lines)+
            "<div style='color:#66778a;font-size:11px;margin-top:5px;'>"
            "竞彩与皇冠分别计算；研究倾向并非已验证投注优势。</div></div>")

def sop_evidence(x):
    """Show short, evidence-derived model assessment, never generic confidence."""
    data=x.get("analysis_sop") or {}
    if not data:
        return ""
    stages=data.get("stages") or {}
    verdict=text(data.get("assessment","数据不足，暂不判断"))
    reason_map={
       "UNVERIFIED_JINGCAI_NUMBER_OR_TEAM_OR_DATE":"竞彩身份待核",
       "INDEPENDENT_MODEL_NOT_FULLY_VERIFIED":"模型证据不足",
       "NO_PRIOR_MARKET_SNAPSHOT":"首次采样，仅有基线",
       "JINGCAI_QUOTE_MISSING_STALE_OR_CLOCK_MISMATCH":"竞彩奖金时间不同步",
       "JINGCAI_QUOTE_AFTER_TIPOFF":"赛后报价已排除",
       "INJURY_DATA_NOT_CONFIRMED":"伤停信息待核",
       "NO_AVAILABLE_JINGCAI_MARKET":"竞彩暂未报价",
       "DUPLICATE_JINGCAI_MATCH_NUMBER":"竞彩编号冲突"
    }
    reasons=[reason_map.get(str(r)) for r in data.get("evidence_reasons",[])]
    reasons=[r for r in reasons if r]
    notes="；".join(reasons[:3]) if reasons else "关键证据已记录"
    gaps=data.get("research_comparison") or {}
    total_gap=gaps.get("total_gap_points")
    diff=("　总分模型-竞彩线："+f(total_gap,True)+"分" if num(total_gap) is not None else "")
    focus=data.get("research_focus") or []
    focus_text=("；".join(text(t) for t in focus[:2]) if focus else "暂无明显模型/竞彩盘口差距")
    return ("<div style='margin:7px 0;padding:8px 9px;border-left:3px solid #889bb2;"
            "background:#f6f8fb;font-size:11px;line-height:1.55;'>"
            "<b>七步分析研判</b>："+verdict+diff+"<div>观察："+focus_text+
            "</div><div>核验："+text(notes)+"</div></div>")

def lottery_label(game):
    """Validated 007 lottery issue code; never manufacture it from report order."""
    import re
    v=game.get("jc_match_label")
    if game.get("jc_match_identity_status")=="VERIFIED_JC_NUMBER" and isinstance(v,str) and re.fullmatch(r"周[一二三四五六日天][0-9]{3}",v):
        return v
    return "竞彩编号待核"

def lottery_sort(game):
    label=lottery_label(game)
    return (0,int(label[-3:])) if label!="竞彩编号待核" else (1,999)

def priority_focus_panel(document):
    """Top-of-report relative model attention; never a promised hit rate."""
    if not document:return ""
    items=document.get("focus_games") or []
    lines=[]
    for item in items:
        side=text(item.get("model_direction"))
        p=num(item.get("model_direction_probability"))
        prob=f(p*100)+"%" if p is not None else "—"
        name=text(item.get("jingcai_number") or "竞彩编号待核")
        home=text(item.get("home_team"));away=text(item.get("away_team"))
        why=text(item.get("explanation"))
        caution="；".join(text(x) for x in (item.get("cautions") or [])[:2])
        contrarian=bool(item.get("contrarian_market_signal"))
        divergence=(("<div style=\'font-size:12px;color:#964c14;\'><b>逆向重点：模型与竞彩去水差 "+f(item.get("model_minus_market_home_pp"),True)+" 个百分点</b> · 保留独立判断，不等于已验证价值</div>") if contrarian else "")
        lines.append("<div style='padding:7px 0;border-bottom:1px solid #d7e2ef;'>"+
           "<b>"+str(item.get("focus_rank"))+" · "+name+"　"+home+" vs "+away+"</b>"+
           "<div>模型倾向：<b>"+side+"</b>　模型概率 "+prob+"</div>"+
           "<div style='font-size:11px;color:#465b73;'>依据："+why+"</div>"+divergence+
           "<div style='font-size:11px;color:#836028;'>风险："+(caution or "请关注临场变化")+"</div></div>")
    if not items:
        lines=["<div>本批次没有通过完整数据核验的重点场次，不强行指定。</div>"]
    return ("<div style='border:1px solid #c8d7eb;background:#f2f6fc;"
       "padding:10px 11px;border-radius:9px;margin:11px 0;line-height:1.6;'>"+
       "<div style='font-size:15px;font-weight:750;'>重点关注场次 · 模型相对排序</div>"+
       "<div style='font-size:11px;color:#5c7088;'>不设固定胜率门槛；动态最多3场。"
       "模型概率不是经保证的真实胜率；不代表投注价值。</div>"+
       "".join(lines)+"</div>")

def independent_market_divergence_panel(document):
    """Market is compared only AFTER the independent model focus is frozen."""
    cases=(document or {}).get("market_divergences") or []
    if not cases:return ""
    lines=[]
    for item in cases:
        p=num(item.get("model_home_probability"))
        q=num(item.get("market_no_vig_home"))
        lines.append("<div style='border-bottom:1px solid #e4e9f1;padding:6px 0;'>"+
            "<b>"+text(item.get("jingcai_number") or "竞彩编号待核")+"　"+
            text(item.get("home_team"))+" vs "+text(item.get("away_team"))+"</b>"+
            "<div>独立模型主胜 "+(f(p*100)+"%" if p is not None else "—")+
            "｜竞彩去水约 "+(f(q*100)+"%" if q is not None else "—")+
            "｜差 "+f(item.get("model_minus_market_home_pp"),True)+" 个百分点</div></div>")
    return ("<div style='padding:10px 11px;margin:10px 0;border:1px solid #dfd5c9;"
        "border-radius:8px;font-size:12px;line-height:1.6;'>"+
        "<b>模型与市场分歧 · 独立观察</b>"+
        "<div style='color:#626f7f;'>仅对照，不改模型胜率，不改变重点排名；分歧不自动等于价值。</div>"+
        "".join(lines)+"</div>")

def render_v2(games,model_map,title,target,mode,priority_focus=None):
    g=sorted(games,key=lambda x:(lottery_sort(x),str(x.get("display_clock") or ""),str(x.get("game_id"))))
    css="font-family:-apple-system,BlinkMacSystemFont,Arial,sans-serif;font-size:14px;color:#1d3045;max-width:540px;margin:0 auto;line-height:1.52;"
    synthetic="模拟" in str(title)
    heading=("模拟报告 · 8场速览" if synthetic else
             "盘口异动 · 重点速览" if mode=="hourly" else "赛前模型 · 比赛速览")
    sub=("以下全部为虚构数据，仅测试排版" if synthetic else
         "北京时间 "+str(target)+" · "+str(len(g))+" 场 · 变化优先（非投注排名）")
    out=["<div style='"+css+"'><div style='padding:10px 12px;background:#eef3fa;border-radius:9px;'>"
         "<div style='font-size:17px;font-weight:750;'>"+text(heading)+"</div>"
         "<div style='color:#617389;font-size:12px;margin-top:3px;'>"+text(sub)+"</div></div>"]
    if priority_focus is not None:
        out.append(priority_focus_panel(priority_focus))
        out.append(independent_market_divergence_panel(priority_focus))
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
                   "<div style='font-size:13px;font-weight:650;'>"+text(lottery_label(x))+"　"+
                   text(x.get("display_clock"))+"　主队："+home+"　｜　客队："+away+"</div>"
                   "<div style='font-size:11px;color:#61758a;margin-top:2px;'>"
                   "主胜 "+(f(win*100)+"%" if win is not None and 0<=win<=1 else "—")+
                   "　· 模总 "+f(total)+"　· 现盘 "+f(q)+
                   "　· 差 "+f(gap,True)+"</div>"+jingcai_status(x)+(verdict_summary(x.get("two_market_verdict")) if not x.get("five_market_forecast") else "")+"<div style='font-size:11px;color:#718297;'>"+text(status)+"</div></div>")
    out.append("<div style='font-size:14px;font-weight:700;margin:14px 0 7px;'>逐场模型与盘口</div>")
    for i,x in enumerate(g,1):
        markets=x.get("markets") or {}
        spread=markets.get("full_spread") or {}
        total=markets.get("full_total") or {}
        pred=model_map.get(str(x.get("game_id")))
        status=x.get("status","FIRST_SNAPSHOT")
        body="<div style='font-size:11px;color:#68788e;'>"+text(lottery_label(x))+" · "+text(x.get("display_clock"))+" · "+text(status_label(status))+"</div>"
        body+="<div style='font-size:15px;font-weight:750;margin:4px 0 7px;'>"+"主队："+text(x.get("home_team"))+"　｜　客队："+text(x.get("away_team"))+"</div>"
        body+=jingcai_status(x, detailed=True)
        if not x.get('five_market_forecast'):
            body+=verdict_summary(x.get('two_market_verdict'))
        body+=sop_evidence(x)
        body+=five_market_panel(x)
        body+=score_prediction(pred)
        body+=probability_disagreement(pred,x)
        body+=market_change(spread,"full_spread")+market_change(total,"full_total")
        body+=compare(pred,spread,total)
        cross=x.get("top10_comparison") or {}
        if cross:
            parts=[]
            for key,label in (("full_spread","让分"),("full_total","总分")):
                q=(cross.get("markets") or {}).get(key) or {}
                count=int(q.get("company_count") or 0)
                if count:
                    changes=q.get("last_capture_company_changes") or []
                    rising=sum(1 for v in changes if num(v.get("delta_line")) is not None and num(v["delta_line"])>0)
                    falling=sum(1 for v in changes if num(v.get("delta_line")) is not None and num(v["delta_line"])<0)
                    parts.append(text(label)+" 已识别 "+str(count)+" 家，盘口中位 "+f(q.get("median_line"))+
                        "，区间 "+f(q.get("line_min"))+"—"+f(q.get("line_max"))+
                        "；同机构跨采样上调 "+str(rising)+" / 下调 "+str(falling))
                else:
                    parts.append(text(label)+" 多机构接口暂无可靠报价")
            body+=("<div style='border:1px solid #dae5f1;padding:8px;border-radius:7px;"
                   "font-size:11px;line-height:1.55;'><b>007多机构横向比较 · 10个真实ID（排序待核）</b><div>"+
                   "</div><div>".join(parts)+"</div>"+
                   "<div>机构名称及排名待核；采集时点不等于实际赔率更新时间；左右方向按007已确认显示规则映射；同线去水概率仅作影子对照。</div></div>")

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
               "统一说明：机构采集时点不等于实际赔率更新时间；左右方向按007已确认显示规则映射。"
               "多机构去水价格只在至少3家报出同一盘口线时计算，并仅作影子对照，不覆盖独立模型概率。"
               "模型得分为均值估算，不代表精确比分；未经时间顺序样本外验证不认定投注优势。</div></div>")
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
    panel=five_market_panel({
        "home_team":"甲","away_team":"乙",
        "five_market_forecast":{"markets":{
            "JINGCAI_WIN":{"status":"DIRECTION_ISSUED","direction":"HOME_WIN","model_direction_probability":.62},
            "JINGCAI_HANDICAP":{"status":"DIRECTION_ISSUED","direction":"HOME_COVER","line":-2.5,
                "signed_home_handicap":2.5,"model_direction_probability":.58,
                "market_consensus":{"market_price_consensus_status":"AVAILABLE_SAME_LINE_MEDIAN",
                    "same_line_company_count":4,"consensus_line":-2.5,
                    "market_price_probability_for_model_direction":.53,
                    "model_minus_market_probability_for_model_direction":.05,
                    "direct_line_matches_price_reference":True}},
            "JINGCAI_TOTAL":{"status":"DIRECTION_ISSUED","direction":"OVER","line":221.5,"model_direction_probability":.57},
            "CROWN_HANDICAP":{"status":"DIRECTION_ISSUED","direction":"AWAY_COVER","line":4.5,
                "signed_home_handicap":-4.5,"model_direction_probability":.61,
                "market_consensus":{"market_price_consensus_status":"AVAILABLE_SAME_LINE_MEDIAN",
                    "same_line_company_count":5,"consensus_line":4.5,
                    "market_price_probability_for_model_direction":.56,
                    "model_minus_market_probability_for_model_direction":.05,
                    "direct_line_matches_price_reference":False}},
            "CROWN_TOTAL":{"status":"DIRECTION_ISSUED","direction":"UNDER","line":224.5,"model_direction_probability":.59}
        }}})
    assert panel.count("模型方向概率 ")==5
    assert "多机构同线去水：4家" in panel
    assert "仅共识线参考" in panel
    assert "模型-市场 +5.0pp" in panel

    q={"game_id":"1","home_team":"甲","away_team":"乙","display_clock":"07:00",
       "status":"LINE_MOVE","markets":{
       "full_spread":{"opening":{"line":-3.5},"previous":{"line":-4.0},"current":{"line":-5.0},"delta_line_previous":-1},
       "full_total":{"opening":{"line":220},"previous":{"line":221},"current":{"line":223},"delta_line_previous":2}}}
    m={"1":{"model_status":"OK","model_probability":{"home":.62},"total_mean":224,"margin_mean_home_minus_away":5,
            "data_quality":{"quality":"PASS"}}}
    q["two_market_verdict"]={"markets":{
        "SPREAD":{"direction":"HOME","line":-5.0,"strength":"LOW"},
        "TOTAL":{"direction":"OVER","line":223.0,"strength":"LOW"}}}
    html=render_v2([q],m,"模拟","2026-10-31","hourly")
    assert "主队 114.5" in html and "客队 109.5" in html and "223.0" in html
    assert "LINE_MOVE" not in html and "让分或总分变动" in html
    assert "主胜 62.0%" in html and "模总 224.0" in html
    assert "研究倾向" in html
    assert "主队：甲" in html and "客队：乙" in html
    assert "方向待核" in html and "NO_BET" in html
    assert "<table" not in html
    assert "八场核心数据" in html and "模型 vs 盘口" in html
    assert "纯模拟·未经真实验收" in html and "模型数据已验收" not in html
    q["jingcai_source_status"]="JINGCAI_PRICES_UNAVAILABLE_DO_NOT_USE_COMMERCIAL_ODDS_AS_PROXY"
    q["jc_007_price_shadow"]={"markets":{"total":{"status":"OBSERVED","data":{
        "opening":{"line":221.5,"first_side":1.66,"second_side":1.74},
        "current":{"line":222.5,"first_side":1.7,"second_side":1.7}}}}}
    jhtml=render_v2([q],m,"赛前模型","2026-10-31","three")
    assert "竞彩赔率（007）" in jhtml and "222.5" in jhtml
    assert "大分 <b>1.70</b>" in jhtml and "小分 <b>1.70</b>" in jhtml
    assert "竞彩赔率（007）" in jhtml
    assert "NO_BET" in jhtml
    q["jc_007_price_shadow"]={"markets":{"win_lose":{"status":"NOT_ON_SALE_USER_CONFIRMED"},
       "handicap":{"status":"OBSERVED","data":{"opening":{"line":-3.5,"first_side":1.7,"second_side":1.7},"current":{"line":-4.5,"first_side":1.65,"second_side":1.75}}}}}
    ns=render_v2([q],m,"赛前模型","2026-10-31","three")
    assert "未开售（用户确认）" in ns
    assert "赔率未核实" not in ns
    q["jc_match_label"]="周五309"
    q["jc_match_no"]="309"
    q["jc_match_identity_status"]="VERIFIED_JC_NUMBER"
    other={**q,"game_id":"2","jc_match_label":"周五318","jc_match_no":"318"}
    result=render_v2([other,q],m,"赛前模型","2026-10-31","three")
    assert result.count("周五309")>=2 and result.count("周五318")>=2
    assert result.index("周五309") < result.index("周五318")
    assert "#01" not in result and "#02" not in result
    other["jc_match_identity_status"]="UNVERIFIED"
    uncertain=render_v2([other],m,"赛前模型","2026-10-31","three")
    assert "竞彩编号待核" in uncertain and "周五318" not in uncertain
    # Regression: 007 first-side price is assigned to HOME.
    exact={**q,"game_id":"728170","home_team":"达拉斯独行侠",
      "away_team":"休斯顿火箭","jc_match_label":"周五314",
      "jc_match_no":"314","jc_match_identity_status":"VERIFIED_JC_NUMBER",
      "jc_007_price_shadow":{"markets":{
       "win_lose":{"status":"OBSERVED","data":{"current":{"first_side":2.95,"second_side":1.19}}},
       "handicap":{"status":"OBSERVED","data":{"opening":{"line":5.5,"first_side":1.75,"second_side":1.65},
          "current":{"line":7.5,"first_side":1.75,"second_side":1.65}}},
       "total":{"status":"OBSERVED","data":{"current":{"line":225.5,"first_side":1.70,"second_side":1.70}}}}}}
    html_exact=render_v2([exact],m,"赛前模型","2026-10-31","three")
    assert "周五314" in html_exact
    assert "主队：达拉斯独行侠　｜　客队：休斯顿火箭" in html_exact
    assert "主胜（达拉斯独行侠）<b>2.95</b>" in html_exact
    assert "客胜（休斯顿火箭）<b>1.19</b>" in html_exact
    assert "达拉斯独行侠 <b>+7.5</b>（受让）" in html_exact
    assert "休斯顿火箭 <b>-7.5</b>（让分）" in html_exact
    assert "大分 <b>1.70</b>" in html_exact and "小分 <b>1.70</b>" in html_exact
    assert "槽1" not in html_exact and "槽2" not in html_exact
    assert "两侧方向仍需核验" not in html_exact
    assert html_exact.count("竞彩赔率（007）")==1
    negative={**exact,"jc_007_price_shadow":{"markets":{"handicap":{
      "status":"OBSERVED","data":{"current":{"line":-6.5,"first_side":1.70,"second_side":1.70}}}}}}
    neg=render_v2([negative],m,"赛前模型","2026-10-31","three")
    assert "达拉斯独行侠 <b>-6.5</b>（让分）" in neg
    assert "休斯顿火箭 <b>+6.5</b>（受让）" in neg
    exact["analysis_sop"]={"assessment":"需要重点复核",
       "research_focus":["大小分：模型与竞彩线差距较大"],
       "research_comparison":{"total_gap_points":5.5},
       "evidence_reasons":["NO_PRIOR_MARKET_SNAPSHOT","INJURY_DATA_NOT_CONFIRMED"]}
    sop_html=render_v2([exact],m,"赛前模型","2026-10-31","three")
    assert sop_html.count("七步分析研判")==1
    assert "需要重点复核" in sop_html and "首次采样，仅有基线" in sop_html
    assert "总分模型-竞彩线：+5.5分" in sop_html
    assert sop_html.count("竞彩赔率（007）")==1
    # 2026-10-31 real board semantics: Toronto favored at raw +5.5,
    # therefore home -5.5; Dallas underdog at raw -6.5 => home +6.5.
    t1=verdict_summary({"markets":{"SPREAD":{"line":5.5,"direction":"HOME","signed_home_handicap":-5.5},
      "TOTAL":{"line":226.5,"direction":"OVER"}}})
    assert "主队让 5.5 分" in t1 and "主队盘口 -5.5" in t1 and "倾向主队赢盘" in t1
    t2=verdict_summary({"markets":{"SPREAD":{"line":-6.5,"direction":"AWAY","signed_home_handicap":6.5},
      "TOTAL":{"line":224.5,"direction":"OVER"}}})
    assert "主队受让 6.5 分" in t2 and "主队盘口 +6.5" in t2 and "倾向客队赢盘" in t2
    assert "主队方向（5.5）" not in t1 and "客队方向（-6.5）" not in t2
    legacy=verdict_summary({"markets":{"SPREAD":{"line":-6.5,"direction":"AWAY",
      "rule":"PROVISIONAL_HOME_HANDICAP_ADD_TO_HOME_MINUS_AWAY"},
      "TOTAL":{"line":224.5,"direction":"OVER"}}})
    assert "旧版方向失效" in legacy and "倾向客队赢盘" not in legacy
    exact["five_market_forecast"]={"markets":{
      "JINGCAI_WIN":{"status":"DIRECTION_ISSUED","direction":"AWAY_WIN"},
      "JINGCAI_HANDICAP":{"status":"DIRECTION_ISSUED","direction":"HOME_COVER","signed_home_handicap":7.5},
      "JINGCAI_TOTAL":{"status":"DIRECTION_ISSUED","direction":"OVER","line":225.5},
      "CROWN_HANDICAP":{"status":"DIRECTION_ISSUED","direction":"AWAY_COVER","signed_home_handicap":-6.5},
      "CROWN_TOTAL":{"status":"DIRECTION_ISSUED","direction":"UNDER","line":229.5}}}
    five_html=render_v2([exact],m,"赛前模型","2026-10-31","three")
    assert five_html.count("五玩法独立研判")==1
    assert "#周五314" not in five_html
    assert "007机构盘口研究" not in five_html
    assert all(i in five_html for i in ("① 竞彩胜负","② 竞彩让分胜负","③ 竞彩大小分","④ 皇冠让分","⑤ 皇冠大小分"))
    assert "主队盘口 +7.5" in five_html and "主队盘口 -6.5" in five_html
    exact["five_market_forecast"]["markets"]["JINGCAI_WIN"]={"status":"NOT_ON_SALE_USER_CONFIRMED"}
    no_sale=render_v2([exact],m,"赛前模型","2026-10-31","three")
    assert "未开售，不计入该玩法命中率" in no_sale
    # Actual 2026-10-31 JC #309 Wizards home (1.44) vs Hornets away (2.06).
    # Discrepancy is between a 9.86% calibrated model and 58.86% no-vig market.
    # Never promote either number to a proven "true" probability.
    extreme={**q,"game_id":"728165","home_team":"华盛顿奇才",
      "away_team":"夏洛特黄蜂","jc_match_label":"周五309",
      "jc_match_identity_status":"VERIFIED_JC_NUMBER",
      "jc_007_price_shadow":{"markets":{"win_lose":{"status":"OBSERVED",
      "data":{"current":{"first_side":1.44,"second_side":2.06}}}}}}
    diag={"model_status":"OK","model_probability":{"home":0.098588},
      "model_probability_raw":{"home":0.306},
      "margin_mean_home_minus_away":-7.982,"total_mean":226.16}
    report=probability_disagreement(diag,extreme)
    assert "主胜概率异常" in report and "校准后 9.9%" in report
    assert "模型原始 30.6%" in report
    assert "007 竞彩去水约 58.9%" in report
    assert probability_disagreement(diag,{**extreme,"jc_007_price_shadow":{"markets":{}}})==""
    print("PUSHPLUS_V2_COMPACT_SELF_TEST_PASS")
