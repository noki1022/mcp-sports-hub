"""Read labelled 007 CP basketball cells and reconcile exact fixture identities."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
import base64
import hashlib
import json
from pathlib import Path
import re

from football_007_cp_totals import BJ, Rows, decode, fetch_cp_page, fixture_id
from verify_007_jc_fixture_identity import comparable

PAGES={"win_lose":"111","handicap":"112","total":"114"}
URL="https://cp.titan007.com/buy/JingCaiBasket.aspx?TypeID={}&OddsType=2"


def parse(raw,market):
    reader=Rows();reader.feed(decode(raw))
    if not any(("typeid="+PAGES[market]) in a.get("action","").lower() for a in reader.forms):
        raise ValueError("CP_BASKET_WRONG_MARKET_PAGE")
    output={}
    for row in reader.rows:
        cells=row["cells"]
        if len(cells)<7 or not re.fullmatch(r"\d{3}",cells[0]["text"]):continue
        mid=fixture_id(cells[4],"HomeTeam")
        if not mid or mid!=fixture_id(cells[6],"GuestTeam"):
            raise ValueError("CP_BASKET_FIXTURE_ID_MISMATCH")
        if mid in output:raise ValueError("CP_BASKET_DUPLICATE_FIXTURE")
        sale=date.fromisoformat(row["sale_day"])
        prefix=("周一","周二","周三","周四","周五","周六","周日")[sale.weekday()]
        bet=row["attrs"]["id"].removeprefix("row_")
        by_id={c["attrs"].get("id"):c for c in cells}
        titles=("大分","小分") if market=="total" else ("主胜","客胜")
        prices=[]
        for i,title in enumerate(titles,1):
            cell=by_id.get(f"cell_{bet}_{i}")
            if cell is None or cell["attrs"].get("title")!=title:
                raise ValueError("CP_BASKET_PRICE_LABEL_MISMATCH")
            try:value=float(cell["text"])
            except ValueError:value=None
            prices.append(value if value is not None and 1<value<=1000 else None)
        line=None
        if market!="win_lose":
            cell=by_id.get(f"cell_{bet}_goal")
            if cell is None or cell["attrs"].get("title")!=("总分" if market=="total" else "让分"):
                raise ValueError("CP_BASKET_LINE_LABEL_MISMATCH")
            try:line=float(cell["text"])
            except ValueError:pass
            if line is not None and not ((80<=line<=400) if market=="total" else (-80<=line<=80)):
                raise ValueError("CP_BASKET_LINE_OUT_OF_RANGE")
        output[mid]={"label":prefix+cells[0]["text"],"sale_day":sale.isoformat(),
            "clock":cells[2]["text"],"home":cells[4]["text"],"away":cells[6]["text"],
            "line":line,"prices":prices,"can_sale":row["attrs"].get("cansale")=="true"}
    if not output:raise ValueError("CP_BASKET_NO_RECOGNIZED_FIXTURES")
    return output


def enrich(board,audit,pages):
    identities=audit.setdefault("jc_007_match_numbers",{"games":{}})
    ids=identities.setdefault("games",{})
    feed=audit.setdefault("jc_007_public_odds_shadow",{"games":[]})
    games={str(g["game_id"]):g for g in feed.get("games",[])}
    for game in board.get("nba_cba_games",[]):
        if game.get("league")!="NBA":continue
        mid=str(game["game_id"])
        tip=datetime.fromisoformat(game["start_time_beijing"]).astimezone(BJ)
        result=games.setdefault(mid,{"game_id":mid,"nba_game_id":game.get("nba_game_id"),
            "home_team":game["home_team"],"away_team":game["away_team"],
            "tipoff_beijing":game["start_time_beijing"],"markets":{}})
        for market,page in pages.items():
            row=page["rows"].get(mid)
            if row is None:continue
            sale=date.fromisoformat(row["sale_day"])
            start=datetime.combine(sale,datetime.min.time(),tzinfo=BJ)+timedelta(hours=12)
            observed=datetime.fromisoformat(page["captured_at_utc"])
            if not (comparable(game["home_team"],[row["home"]]) and
                    comparable(game["away_team"],[row["away"]]) and
                    start<=tip<=start+timedelta(days=1) and
                    row["clock"]==tip.strftime("%H:%M") and observed<tip):
                raise ValueError("CP_BASKET_BOARD_IDENTITY_MISMATCH_"+mid)
            old=ids.get(mid,{})
            if old.get("status")=="VERIFIED_JC_NUMBER" and old.get("label")!=row["label"]:
                raise ValueError("CP_XML_BASKET_NUMBER_CONFLICT_"+mid)
            ids[mid]={"game_id":mid,"status":"VERIFIED_JC_NUMBER","label":row["label"],
                "match_no":row["label"][-3:],"reason":None,"source":page["url"],
                "tipoff_beijing":game["start_time_beijing"],"captured_at_utc":page["captured_at_utc"]}
            if None in row["prices"] or (market!="win_lose" and row["line"] is None):continue
            current={"first_side":row["prices"][0],"second_side":row["prices"][1]}
            if market!="win_lose":current["line"]=row["line"]
            result["markets"][market]={"status":"OBSERVED",
                "data":{"current":current},"source_url":page["url"],
                "captured_at_utc":page["captured_at_utc"],
                "direction_slot_order_verified":True}
    feed["games"]=list(games.values())
    feed["captured_at_utc"]=max((p["captured_at_utc"] for p in pages.values()),default=feed.get("captured_at_utc"))
    feed["nba_coverage"]={k:sum(g["markets"].get(k,{}).get("status")=="OBSERVED" for g in games.values()) for k in PAGES}
    feed["all_three_market_games"]=sum(all(g["markets"].get(k,{}).get("status")=="OBSERVED" for k in PAGES) for g in games.values())
    identities.update(verified=sum(g.get("status")=="VERIFIED_JC_NUMBER" for g in ids.values()),
        numbered_total=sum(bool(g.get("label")) for g in ids.values()),total_games=len(games))
    audit["verified_games_with_all_three"]=feed["all_three_market_games"]
    for market,code in (("WIN_LOSE","win_lose"),("HANDICAP_WIN_LOSE","handicap"),("TOTAL","total")):
        if code in pages:
            audit.setdefault("source_status",{}).setdefault(market,{}).update({
                "url":pages[code]["url"],"status":"VERIFIED_007_CP_LABELLED_CELLS",
                "matched_games":feed["nba_coverage"][code],"live_pricing_rows":len(pages[code]["rows"])})
    audit["status"]="VERIFIED_007_CP_LABELLED_MARKETS" if feed["all_three_market_games"]==len(games) else "PARTIAL_007_JC_MARKET_COVERAGE"
    return audit


def capture(board,audit,raw_path=Path("nba_jingcai_cp_source.json")):
    pages={};sources={};errors={}
    with ThreadPoolExecutor(max_workers=3) as pool:
        pending={market:pool.submit(fetch_cp_page,URL.format(tid)) for market,tid in PAGES.items()}
        for market,future in pending.items():
            try:
                raw=future.result()
                stamp=datetime.now(timezone.utc).isoformat()
                sources[market]={"url":URL.format(PAGES[market]),"captured_at_utc":stamp,
                    "sha256":hashlib.sha256(raw).hexdigest(),"raw_base64":base64.b64encode(raw).decode("ascii")}
                pages[market]={"url":sources[market]["url"],"captured_at_utc":stamp,"rows":parse(raw,market)}
            except (OSError,ValueError,RuntimeError) as exc:
                errors[market]=type(exc).__name__+":"+str(exc)[:180]
    raw_path.write_text(json.dumps({"captured_at_utc":datetime.now(timezone.utc).isoformat(),
        "target_date":board["requested_display_date"],"sources":sources,"errors":errors},ensure_ascii=False)+"\n",encoding="utf-8")
    audit["cp_source_errors"]=errors
    return enrich(board,audit,pages)
