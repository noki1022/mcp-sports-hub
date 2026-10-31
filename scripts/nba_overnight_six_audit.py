#!/usr/bin/env python3
"""Six Beijing hourly captures with immutable source/model/five evidence."""
import argparse,json,hashlib
from pathlib import Path
SLOTS=("0030","0130","0230","0330","0430","0530")
def digest(root,day):
    root=Path(root)/"reports/overnight-six"/day
    done=[];miss=[]
    for slot in SLOTS:
        base=root/slot
        try:
            manifest=json.loads((base/"evidence.json").read_text())
            assert manifest["slot"]==slot and manifest["target_date"]==day
            assert manifest["status"]=="CAPTURE_AND_ANALYSIS_COMPLETE"
            for name,expected in manifest["files"].items():
                assert hashlib.sha256((base/name).read_bytes()).hexdigest()==expected
            done.append({"slot":slot,"games":manifest["games"],"capture":manifest["captured_at_utc"]})
        except (OSError,ValueError,AssertionError,KeyError,TypeError):
            miss.append({"slot":slot,"reason":"无完整且可校验的抓取和分析证据"})
    return {"target_date":day,"expected":6,"completed":len(done),"missing":miss,"completed_slots":done,
            "state":"COMPLETE" if len(done)==6 else "INCOMPLETE"}
def capture(root,day,slot,joined,model,five,movement,run):
    if slot not in SLOTS:raise ValueError("NOT_SILENT_OVERNIGHT_SLOT")
    if joined.get("requested_display_date")!=day or five.get("target_date")!=day:raise ValueError("WRONG_BEIJING_DAY")
    ids={str(x.get("game_id")) for x in joined.get("nba_cba_games",[]) if x.get("league")=="NBA"}
    if not ids or ids!={str(x.get("game_id")) for x in five.get("games",[])}:raise ValueError("FIVE_BOARD_MISMATCH")
    if not ids.issubset({str(x.get("game_id")) for x in model.get("games",[])}):raise ValueError("MODEL_BOARD_MISMATCH")
    root=Path(root)/"reports/overnight-six"/day/slot
    if root.exists():raise ValueError("OVERNIGHT_SLOT_IMMUTABLE")
    root.mkdir(parents=True)
    files={};docs={"joined.json":joined,"model.json":model,"five.json":five,"movement.json":movement}
    for name,doc in docs.items():
        content=(json.dumps(doc,ensure_ascii=False,indent=2,sort_keys=True)+"\n").encode()
        (root/name).write_bytes(content);files[name]=hashlib.sha256(content).hexdigest()
    manifest={"slot":slot,"target_date":day,"run_id":str(run),"games":len(ids),
      "captured_at_utc":joined.get("captured_at_utc"),"status":"CAPTURE_AND_ANALYSIS_COMPLETE","files":files}
    (root/"evidence.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n")
    return manifest
def test():
    from tempfile import TemporaryDirectory
    with TemporaryDirectory() as t:
        d="2026-11-01";joined={"requested_display_date":d,"captured_at_utc":"2026-10-31T16:30:00Z",
           "nba_cba_games":[{"game_id":"101","league":"NBA"}]}
        five={"target_date":d,"games":[{"game_id":"101"}]}
        model={"games":[{"game_id":"101"}]}
        r=capture(t,d,"0030",joined,model,five,{},42)
        assert digest(t,d)["completed"]==1 and len(digest(t,d)["missing"])==5
        try:capture(t,d,"0030",joined,model,five,{},43)
        except ValueError:pass
        else:raise AssertionError("SLOT_OVERWRITE_ALLOWED")
        p=Path(t)/"reports/overnight-six"/d/"0030"/"five.json"
        p.write_text("CORRUPT")
        assert digest(t,d)["completed"]==0
    print("SIX_SILENT_HOURLY_EVIDENCE_TEST_PASS")
if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("action",choices=["capture","digest","self-test"])
    p.add_argument("--root",default=".");p.add_argument("--day");p.add_argument("--slot")
    p.add_argument("--joined");p.add_argument("--model");p.add_argument("--five");p.add_argument("--movement")
    p.add_argument("--run");p.add_argument("--out");a=p.parse_args()
    if a.action=="self-test":test()
    elif a.action=="digest":
        x=digest(a.root,a.day)
        if a.out:Path(a.out).write_text(json.dumps(x,ensure_ascii=False,indent=2)+"\n")
        print("OVERNIGHT_SIX_AUDIT",x["completed"],"/6",x["missing"])
    else:
        get=lambda p:json.loads(Path(p).read_text())
        x=capture(a.root,a.day,a.slot,get(a.joined),get(a.model),get(a.five),get(a.movement),a.run)
        print("OVERNIGHT_SILENT_SNAPSHOT_FROZEN",x["slot"],x["games"])
