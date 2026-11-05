#!/usr/bin/env python3
"""Strict, fail-closed point-in-time sample admission for NBA and football.

Labels are a separate postgame input and NEVER allowed in model features.
Training / tuning / calibration / untouched evaluation must be disjoint with
an explicit temporal embargo. This module only validates and emits a manifest;
it does not retrain, send notifications, or replace live predictions.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import re

SCHEMA = "sports-pit-training-admission-v1"
SPORTS = {"basketball": "NBA", "football": "FOOTBALL"}
SPLITS = ("fit", "tune", "calibration", "holdout")
LEAK_WORDS = re.compile(
    r"(^|[_\W])(final|result|outcome|settlement|score|winner|won|"
    r"closing|postgame|postmatch|actual|label|target|future)([_\W]|$)", re.I
)


def aware(value):
    if not isinstance(value, str):
        raise ValueError("MISSING_SOURCE_TIMESTAMP")
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("INVALID_TIMESTAMP") from exc
    if dt.tzinfo is None:
        raise ValueError("NAIVE_TIMESTAMP")
    return dt.astimezone(timezone.utc)


def sha256(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def fail(reason):
    raise ValueError(reason)


def no_leaky_keys(obj, prefix=""):
    if isinstance(obj, dict):
        for key, value in obj.items():
            if not isinstance(key, str) or LEAK_WORDS.search(key):
                fail("POSTGAME_OR_TARGET_FIELD_IN_FEATURES:" + prefix + str(key))
            no_leaky_keys(value, prefix + key + ".")
    elif isinstance(obj, list):
        for i, value in enumerate(obj):
            no_leaky_keys(value, prefix + str(i) + ".")
    elif obj is None or isinstance(obj, (str, bool, int)):
        return
    elif isinstance(obj, float):
        if not math.isfinite(obj):
            fail("NONFINITE_FEATURE")
    else:
        fail("INVALID_FEATURE_VALUE")


def check_feature(row, cutoff):
    if not isinstance(row, dict):
        fail("FEATURE_ROW_NOT_OBJECT")
    keys = {"sport", "match_id", "kickoff_utc", "decision_utc", "source_sha256",
            "capture_run_id", "model_version", "features"}
    if set(row) != keys:
        fail("UNEXPECTED_FEATURE_ROW_FIELDS")
    if row["sport"] not in SPORTS or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", str(row["match_id"])):
        fail("INVALID_SPORT_OR_MATCH_ID")
    if not re.fullmatch(r"[0-9a-f]{64}", str(row["source_sha256"])):
        fail("MISSING_RAW_SOURCE_HASH")
    if not re.fullmatch(r"[0-9]{1,20}", str(row["capture_run_id"])):
        fail("MISSING_CAPTURE_RUN")
    if not isinstance(row["model_version"], str) or not row["model_version"].strip():
        fail("MISSING_MODEL_VERSION")
    decision, kickoff = aware(row["decision_utc"]), aware(row["kickoff_utc"])
    if decision >= kickoff or decision > cutoff:
        fail("POST_KICKOFF_OR_POST_CUTOFF_DECISION")
    if not isinstance(row["features"], dict) or not row["features"]:
        fail("EMPTY_FEATURE_SET")
    for name, item in row["features"].items():
        if not isinstance(name, str) or LEAK_WORDS.search(name):
            fail("POSTGAME_OR_TARGET_FEATURE_NAME")
        if not isinstance(item, dict) or set(item) != {"value", "observed_at_utc", "available_at_utc"}:
            fail("FEATURE_REQUIRES_OBSERVED_AND_AVAILABLE_TIMES")
        observed, available = aware(item["observed_at_utc"]), aware(item["available_at_utc"])
        if observed > available or available > decision or available >= kickoff:
            fail("FEATURE_AVAILABLE_AFTER_DECISION_OR_KICKOFF")
        no_leaky_keys(item["value"], name + ".")
    return (row["sport"], str(row["match_id"])), kickoff, decision


def check_label(row, identity, kickoff):
    if not isinstance(row, dict):
        fail("INVALID_LABEL_ROW")
    expected = {"sport", "match_id", "result_verified_utc",
                "result_source_sha256", "verified_final", "outcome"}
    if set(row) != expected:
        fail("LABEL_SCHEMA_MISMATCH")
    if (row.get("sport"), str(row.get("match_id"))) != identity:
        fail("RESULT_MATCH_ID_MISMATCH")
    if row["verified_final"] is not True:
        fail("UNVERIFIED_RESULT_NOT_ELIGIBLE")
    if not re.fullmatch(r"[0-9a-f]{64}", str(row["result_source_sha256"])):
        fail("RESULT_SOURCE_HASH_MISSING")
    if aware(row["result_verified_utc"]) <= kickoff:
        fail("RESULT_VERIFIED_BEFORE_KICKOFF")
    outcome = row["outcome"]
    if not isinstance(outcome, dict) or not outcome:
        fail("MISSING_LABELS")
    # No outcomes in the model inputs; do not infer scores from sportsbook lines.
    for k, v in outcome.items():
        if not isinstance(k, str) or not k or isinstance(v, (list, dict)) or v is None:
            fail("INVALID_LABEL_VALUE")
        if isinstance(v, float) and not math.isfinite(v):
            fail("NONFINITE_LABEL")
    return outcome


def index_records(rows, *, label):
    mapped = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("sport"), str):
            fail("INVALID_" + label + "_ENTRY")
        key = (row["sport"], str(row.get("match_id")))
        if key in mapped:
            fail("DUPLICATE_" + label + "_MATCH")
        mapped[key] = row
    return mapped


def boundaries(config):
    if not isinstance(config, dict) or set(config) != {"fit_before_utc", "tune_before_utc",
                                                       "calibration_before_utc", "holdout_before_utc",
                                                       "embargo_days"}:
        fail("INVALID_CHRONOLOGICAL_SPLIT_CONFIG")
    times = [aware(config[k]) for k in ("fit_before_utc", "tune_before_utc",
                                        "calibration_before_utc", "holdout_before_utc")]
    gap = config["embargo_days"]
    if type(gap) is not int or not 1 <= gap <= 30:
        fail("EMBARGO_MUST_BE_1_TO_30_DAYS")
    if not all(a + timedelta(days=gap) < b for a, b in zip(times, times[1:])):
        fail("SPLITS_OVERLAP_OR_INSUFFICIENT_EMBARGO")
    return times, gap


def assign(kickoff, times, embargo):
    previous = None
    for idx, endpoint in enumerate(times):
        if previous is None:
            if kickoff < endpoint:
                return SPLITS[idx]
        elif previous + timedelta(days=embargo) <= kickoff < endpoint:
            return SPLITS[idx]
        elif previous <= kickoff < previous + timedelta(days=embargo):
            return "embargo"
        previous = endpoint
    return "out_of_range"


def admit(features, labels, config):
    cutoffs, embargo_days = boundaries(config)
    source_index = index_records(features, label="FEATURE")
    label_index = index_records(labels, label="RESULT")
    if set(source_index) != set(label_index):
        fail("FEATURE_RESULT_IDENTITY_SET_MISMATCH")
    manifest = []
    counts = Counter()
    for key in sorted(source_index):
        source = source_index[key]
        identity, kickoff, decision = check_feature(source, cutoffs[-1])
        check_label(label_index[key], identity, kickoff)
        split = assign(kickoff, cutoffs, embargo_days)
        counts[split] += 1
        row = {"sport": key[0], "match_id": key[1], "split": split,
               "kickoff_utc": kickoff.isoformat(), "decision_utc": decision.isoformat(),
               "capture_run_id": source["capture_run_id"], "source_sha256": source["source_sha256"],
               "result_source_sha256": label_index[key]["result_source_sha256"],
               "feature_sha256": sha256(source), "label_sha256": sha256(label_index[key]),
               "model_version": source["model_version"]}
        manifest.append(row)
    return {"schema_version": SCHEMA, "no_same_game_outcomes_in_model_inputs": True,
            "partitions_fixed_before_scoring": True, "embargo_days": embargo_days,
            "split_boundaries_utc": [x.isoformat() for x in cutoffs],
            "counts": {key: counts[key] for key in (*SPLITS, "embargo", "out_of_range")},
            "records": manifest,
            "usable_count": sum(counts[x] for x in SPLITS),
            "admission_only": True, "production_model_modified": False}


def read_jsonl(path):
    data = []
    for number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            data.append(json.loads(line))
        except ValueError as exc:
            raise ValueError("INVALID_JSONL_LINE_" + str(number)) from exc
    return data


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--features-jsonl", required=True)
    p.add_argument("--results-jsonl", required=True)
    p.add_argument("--split-config", required=True)
    p.add_argument("--out", required=True)
    a = p.parse_args()
    config = json.loads(Path(a.split_config).read_text(encoding="utf-8"))
    output = admit(read_jsonl(a.features_jsonl), read_jsonl(a.results_jsonl), config)
    dest = Path(a.out)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("SPORTS_PIT_SAMPLE_ADMISSION", output["usable_count"], output["counts"],
          "NO_LIVE_MODEL_CHANGE")


if __name__ == "__main__":
    main()
