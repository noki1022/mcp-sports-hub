#!/usr/bin/env python3
"""Fail-closed final NBA dataset admission policy.

No raw input or research candidates can be silently promoted to production.
Outputs only a small verdict JSON in /tmp. Satisfying a positive row count is
insufficient: independent provenance, rights, clock semantics, anti-leakage and
holdout isolation must ALL be witnessed in machine-readable attestations.
"""
import argparse,json,hashlib,csv
from pathlib import Path
ALLOWED={"scores","team_boxscores","player_boxscores","odds"}
REQUIRED=("source_url","source_sha256","license_verified","upstream_provenance_independent",
          "unique_game_keys","score_crosschecked","historical_asof_verified",
          "train_before_holdout","no_same_day_features","source_rows_valid",
          "cross_source_disagreements")
def evaluate(data):
    results={}
    for kind in sorted(ALLOWED):
        x=data.get(kind,{})
        reasons=[]
        for k in REQUIRED:
            if k not in x:reasons.append("MISSING_ATTESTATION_"+k.upper())
        for k in ("license_verified","upstream_provenance_independent","unique_game_keys",
                  "score_crosschecked","historical_asof_verified","train_before_holdout",
                  "no_same_day_features","source_rows_valid"):
            if x.get(k) is not True:reasons.append("GATE_FALSE_"+k.upper())
        if x.get("cross_source_disagreements")!=0:reasons.append("DISAGREEMENTS_NOT_ZERO")
        digest=x.get("source_sha256","")
        if len(digest)!=64 or any(c not in "0123456789abcdef" for c in digest):
            reasons.append("SOURCE_HASH_NOT_SHA256")
        if not str(x.get("source_url","")).startswith("https://"):
            reasons.append("SOURCE_URL_UNVERIFIED")
        if kind=="odds":
            for name in ("quote_timestamp_precise","pre_tip_quote_proven",
                         "bookmaker_identity_verified","market_orientation_verified",
                         "independent_tip_timestamp_verified"):
                if x.get(name) is not True:reasons.append("ODDS_GATE_FALSE_"+name.upper())
        if kind=="player_boxscores" and x.get("complete_game_player_score_reconciliation") is not True:
            reasons.append("PLAYER_TEAM_TOTALS_NOT_VERIFIED")
        if kind=="team_boxscores" and x.get("reciprocal_team_rows_verified") is not True:
            reasons.append("TEAM_PAIR_NOT_VERIFIED")
        results[kind]={"status":"ADMITTED" if not reasons else "QUARANTINED",
                       "accepted_rows":int(x.get("rows",0)) if not reasons else 0,
                       "reasons":sorted(set(reasons))}
    return {"protocol":"2026-10-29 final NBA strict admission v1",
            "production_promote_allowed":all(x["status"]=="ADMITTED" for x in results.values()),
            "per_dataset":results,"unattested_sources_are_never_promoted":True}
def self_test():
    assert not evaluate({})["production_promote_allowed"]
    good={"source_url":"https://example.org","source_sha256":"a"*64,
          "license_verified":True,"upstream_provenance_independent":True,
          "unique_game_keys":True,"score_crosschecked":True,"historical_asof_verified":True,
          "train_before_holdout":True,"no_same_day_features":True,"source_rows_valid":True,
          "cross_source_disagreements":0,"rows":10,
          "reciprocal_team_rows_verified":True,
          "complete_game_player_score_reconciliation":True,
          "quote_timestamp_precise":True,"pre_tip_quote_proven":True,
          "bookmaker_identity_verified":True,"market_orientation_verified":True,
          "independent_tip_timestamp_verified":True}
    assert evaluate({k:good for k in ALLOWED})["production_promote_allowed"]
    failed=dict(good,license_verified=False)
    assert evaluate({k:failed for k in ALLOWED})["per_dataset"]["scores"]["accepted_rows"]==0
    assert evaluate({"scores":good})["per_dataset"]["odds"]["status"]=="QUARANTINED"
    print("FINAL_ADMISSION_GATE_SELF_TEST_PASS")
def main():
    p=argparse.ArgumentParser()
    p.add_argument("--input",type=Path)
    p.add_argument("--out",type=Path,default=Path("/tmp/nba_final_admission_verdict.json"))
    p.add_argument("--self-test",action="store_true")
    a=p.parse_args()
    if a.self_test:return self_test()
    x=json.loads(a.input.read_text()) if a.input else {}
    verdict=evaluate(x)
    if not str(a.out.resolve()).startswith("/tmp/"):raise SystemExit("OUTPUT_MUST_BE_EPHEMERAL")
    a.out.write_text(json.dumps(verdict,indent=2,ensure_ascii=False))
    print("NBA_FINAL_DATA_ADMISSION "+json.dumps(verdict,sort_keys=True))
    if not verdict["production_promote_allowed"]:print("PRODUCTION_TRAINING_MUTATION_BLOCKED")
if __name__=="__main__":main()
