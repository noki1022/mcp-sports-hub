#!/usr/bin/env python3
"""Regression: real 15-match archived slate, 14 verified + 1 user-confirmed
number; original model decisions and market odds must not change."""
import json,sys,subprocess,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
sys.path.insert(0,str(ROOT/"analysis"))
from verify_007_jc_push_numbering import verify,manual_confirmations
from nba_five_markets import make

def load(name):
    return json.loads((ROOT/"reports/daily/2026-11-03/1800"/name).read_text(encoding="utf-8"))
def main():
    joined=load("titan007_three_joined.json")
    orig_jc=load("nba_jingcai_three_market.json")
    model=load("nba_model_analysis.json")
    cons=load("nba_market_consensus.json")
    assert len(joined["nba_cba_games"])==15
    match=next(x for x in joined["nba_cba_games"] if x["game_id"]=="728298")
    assert (match["nba_game_id"],match["home_team"],match["away_team"])==(
        "401909907","克里夫兰骑士","俄克拉荷马城雷霆")
    assert orig_jc["jc_007_match_numbers"]["verified"]==14
    assert orig_jc["jc_007_match_numbers"]["games"]["728298"]["reason"]=="HOME_AWAY_MISMATCH"
    # Simulate the exact original feed identity mismatch, with a
    # source-reversed row. User confirmation is display-only.
    fixture=("1^meta$728298^2026,10,3,08,00,00^0^^周一302^7^11^"
        "俄克拉荷马城雷霆,雷霆^12^克里夫兰骑士,骑士").encode()
    result=verify({"requested_display_date":"2026-11-03","nba_cba_games":[match]},fixture)
    entry=result["games"]["728298"]
    assert result["user_confirmed"]==1 and result["verified"]==0
    assert (entry["label"],entry["match_no"],entry["status"])==(
        "周一302","302","USER_CONFIRMED_JC_NUMBER")
    jc=json.loads(json.dumps(orig_jc))
    jc["jc_007_match_numbers"]["games"]["728298"]=entry
    jc["jc_007_match_numbers"]["user_confirmed"]=1
    jc["jc_007_match_numbers"]["numbered_total"]=15
    assert {g["label"] for g in jc["jc_007_match_numbers"]["games"].values()
            if g.get("label") and g["game_id"]!="728298"}=={
        g["label"] for g in orig_jc["jc_007_match_numbers"]["games"].values()
            if g.get("label")}
    original=make(joined,model,orig_jc,{},cons)
    revised=make(joined,model,jc,{},cons)
    a={x["game_id"]:x for x in original["games"]}
    b={x["game_id"]:x for x in revised["games"]}
    assert set(a)==set(b)
    assert all(a[gid]["markets"]==b[gid]["markets"] for gid in a),(
        "DISPLAY_NUMBER_MUST_NOT_CHANGE_ORIGINAL_MODEL_FIVE_PLAYS")
    assert b["728298"]["jingcai_number"]=="周一302"
    assert b["728298"]["jingcai_number_status"]=="USER_CONFIRMED"
    assert a["728298"]["jingcai_number"] is None
    assert all(a[gid]["jingcai_number"]==b[gid]["jingcai_number"]
               for gid in a if gid!="728298")
    with tempfile.TemporaryDirectory() as tmp:
        p=Path(tmp);j=p/"jingcai.json";five=p/"five.json"
        j.write_text(json.dumps(jc,ensure_ascii=False))
        five.write_text(json.dumps(revised,ensure_ascii=False))
        preview=p/"iphone.html"
        args=[sys.executable,str(ROOT/"scripts/pushplus_mobile.py"),
            "--mode","three",
            "--joined",str(ROOT/"reports/daily/2026-11-03/1800/titan007_three_joined.json"),
            "--model",str(ROOT/"reports/daily/2026-11-03/1800/nba_model_analysis.json"),
            "--movement",str(ROOT/"reports/daily/2026-11-03/1800/titan007_three_movement.json"),
            "--jingcai",str(j),"--five",str(five),
            "--preview",str(preview),"--status",str(p/"status.json")]
        subprocess.run(args,cwd=ROOT,check=True)
        text=preview.read_text(encoding="utf-8")
        assert "周一302" in text, "IPHONE_PUSH_MISSING_USER_CONFIRMED_302"
        assert "周一303" in text and "周一316" in text, "PREEXISTING_MATCH_NUMBER_LOST"
        assert "ID3" not in text and "玩法" not in text
        print("ACTUAL_15_GAME_MOBILE_PUSH_JC_302_CORRECT_14_UNCHANGED_PASS")
    print("MANUAL_NUMBER_ONLY_NO_MODEL_ODDS_OR_TEAM_DIRECTION_MUTATION_PASS")

if __name__=="__main__":main()
