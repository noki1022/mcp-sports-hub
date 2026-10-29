#!/usr/bin/env python3
"""Build tri-route verified score training candidate; no automatic promotion.

Makes an auditable subset after strict three-route score agreement. Holds
ambiguous upstream rights and independence in quarantine.
"""
import csv,io,json,hashlib,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from nba_538_training_source import SOURCE,LINE_SHEET,bounded_fetch,verify as oldverify
from nba_2015_22_training_expansion import UPSTREAM,crossverify as newverify
from nba_independent_route_score_audit import independent_game_index
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
import kaggle_nba_foundation_batches as kb
COLUMNS=["date","home","away","home_points","away_points","playoffs"]
def assemble():
    reference=bounded_fetch(LINE_SHEET,limit=9_000_000)
    earlier,_=oldverify(bounded_fetch(SOURCE,limit=25_000_000),reference)
    later,_=newverify(bounded_fetch(UPSTREAM,limit=22_000_000),reference)
    total,members=kb.archive_entries()
    third_blob=kb.fetch_member(total,members["csv/games_index.csv"])
    third,_=independent_game_index(third_blob)
    accepted=[];rejected={"no_third_route_match":0,"third_route_score_conflict":0}
    for row in earlier+later:
        key=(row["date"],row["home"],row["away"])
        points=third.get(key)
        if points is None:rejected["no_third_route_match"]+=1;continue
        if points!=(row["home_points"],row["away_points"]):
            rejected["third_route_score_conflict"]+=1;continue
        if set(row)!=set(COLUMNS) or not "2007-08-01"<=row["date"]<"2022-08-01":
            raise ValueError("NON_APPROVED_ROW_OR_DATE")
        accepted.append(row)
    accepted.sort(key=lambda r:(r["date"],r["home"],r["away"]))
    if len(set((r["date"],r["home"],r["away"]) for r in accepted))!=len(accepted):
        raise ValueError("DUPLICATE_KEYS")
    return accepted,rejected,hashlib.sha256(third_blob).hexdigest()
def main():
    if "--self-test" in sys.argv:
        assert len(COLUMNS)==6 and "odds" not in COLUMNS
        print("TRIROUTE_BUILD_TEST_PASS")
        return
    rows,rejected,digest=assemble()
    if len(rows)<18000 or rejected["third_route_score_conflict"]>5:
        raise ValueError("STRICT_ADMISSION_COVERAGE_OR_CONFLICT_FAILURE")
    out=Path("/tmp/nba-three-route-candidate")
    out.mkdir(exist_ok=True)
    csv_path=out/"nba_scores_three_route_verified_2007_2022.csv"
    with csv_path.open("w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,COLUMNS);w.writeheader();w.writerows(rows)
    meta={"status":"QUARANTINED_TRAINING_CANDIDATE","count":len(rows),
          "cross_route_rejections":rejected,"sha256":hashlib.sha256(csv_path.read_bytes()).hexdigest(),
          "third_route_sha256":digest,"only_score_label_columns":COLUMNS,
          "no_same_day_feature_generation_in_this_artifact":True,
          "upstream_rights_and_independence_still_unresolved":True,
          "production_training_promoted":False}
    (out/"manifest.json").write_text(json.dumps(meta,indent=2))
    print("TRIROUTE_TRAINING_CANDIDATE "+json.dumps(meta,sort_keys=True),flush=True)
if __name__=="__main__":main()
