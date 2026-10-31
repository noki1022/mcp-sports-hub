#!/usr/bin/env python3
"""Point-in-time NBA official injury -> model probability adapter.

Never invent player value from an Out/Questionable label. A separately fitted,
walk-forward-validated player-impact artifact is required for numerical effects.
The artifact's effect is *relative to historical expected availability*, because
the pre-injury team model already contains normal roster absences.
"""
from __future__ import annotations

import math
from datetime import datetime, date, timezone

STATUSES = {"Out": 0.0, "Available": 1.0}
PENDING = {"Questionable", "Doubtful", "Probable"}
Z = {"50": .67448975, "80": 1.28155157, "95": 1.95996398}
MAX_PLAYER_MARGIN = 12.0
MAX_PLAYER_TOTAL = 14.0


def stamp(value):
    try:
        d = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return d.astimezone(timezone.utc) if d.tzinfo else None
    except (ValueError, TypeError):
        return None


def finite(value):
    if isinstance(value, bool):
        return None
    try:
        n = float(value)
        return n if math.isfinite(n) else None
    except (ValueError, TypeError):
        return None


def normal_greater(mean, std, threshold):
    return .5 * math.erfc((threshold - mean) / (math.sqrt(2) * std))


def isotonic(cal, p):
    knots = (cal or {}).get("probability_knots") or []
    rates = (cal or {}).get("rate_knots") or []
    if not knots or len(knots) != len(rates):
        return p
    if p <= knots[0]:
        return float(rates[0])
    for i in range(1, len(knots)):
        if p <= knots[i]:
            a = float(knots[i - 1]); b = float(knots[i])
            w = (p - a) / (b - a) if b > a else 1.0
            return float(rates[i - 1] * (1 - w) + rates[i] * w)
    return float(rates[-1])


def _qualified_catalog(catalog, tip):
    if not isinstance(catalog, dict) or catalog.get("schema_version") != "nba-player-impact-v1":
        return False
    validation = catalog.get("validation") or {}
    # The source MUST carry evidence from a disjoint chronological backtest.
    if validation.get("status") != "WALK_FORWARD_PASS" or (finite(validation.get("test_games")) or 0) < 200:
        return False
    if not catalog.get("source_hash") or not catalog.get("model_version"):
        return False
    if not stamp(catalog.get("captured_at_utc")) or stamp(catalog["captured_at_utc"]) >= tip:
        return False
    try:
        trained = date.fromisoformat(str(catalog["trained_through"])[:10])
    except (ValueError, KeyError, TypeError):
        return False
    return trained < tip.date()


def _name(value):
    return " ".join(str(value or "").casefold().replace(",", " ").split())


def adjust(pred, injury, source, tipoff, impact_catalog=None):
    """Returns a COPY of a model prediction. Both probability and mean are updated.

    Missing evidence is a no-op with a visible reason, never a phantom adjustment.
    """
    out = dict(pred)
    meta = {"status": "PENDING_OFFICIAL_INJURY", "adjusted": False,
            "validation": "NOT_VERIFIED", "players": [],
            "margin_delta": 0.0, "total_delta": 0.0}
    out["injury_adjustment"] = meta
    tip = stamp(tipoff)
    capture = stamp((injury or {}).get("source_captured_at_utc"))
    if (not tip or not capture or capture >= tip or source != "official NBA injury PDF"
            or (injury or {}).get("quality") not in ("PUBLISHED_AFFECTED", "PUBLISHED_LISTED")
            or any((injury or {}).get(s, {}).get("report_state") != "PUBLISHED"
                   for s in ("home", "away"))):
        return out
    base_margin = finite(pred.get("margin_mean_home_minus_away"))
    base_total = finite(pred.get("total_mean"))
    ms = finite(pred.get("margin_sigma")); ts = finite(pred.get("total_sigma"))
    if any(x is None for x in (base_margin, base_total, ms, ts)) or ms <= 0 or ts <= 0:
        meta["status"] = "BASE_MODEL_UNAVAILABLE"
        return out
    selected = []
    for side in ("home", "away"):
        for player in injury[side].get("players", []):
            if player.get("status") in STATUSES or player.get("status") in PENDING:
                selected.append((side, player))
    if not selected:
        meta.update(status="NO_REPORTED_PLAYER_ABSENCES", validation="NOT_REQUIRED")
        return out
    if not _qualified_catalog(impact_catalog, tip):
        meta["status"] = "PLAYER_IMPACT_BACKTEST_MISSING_OR_STALE"
        return out
    entries = {}
    for item in impact_catalog.get("players", []):
        key = (item.get("team"), _name(item.get("name")))
        if key in entries:
            meta["status"] = "DUPLICATE_PLAYER_IMPACT"; return out
        entries[key] = item
    delta_margin = delta_total = variance_margin = variance_total = 0.0
    for side, player in selected:
        status = player.get("status")
        if status in PENDING:
            # Probability-of-playing must be learned from date-stamped outcomes,
            # never guessed from words like Questionable.
            calibrated = (impact_catalog.get("availability_probabilities") or {}).get(status)
            probability = finite((calibrated or {}).get("p_play")) if isinstance(calibrated, dict) else None
            sample = finite((calibrated or {}).get("sample")) if isinstance(calibrated, dict) else None
            if probability is None or not 0 <= probability <= 1 or sample is None or sample < 100:
                meta["status"] = "UNCALIBRATED_AVAILABILITY_STATUS"; return out
        else:
            probability = STATUSES[status]
        team = pred.get(side)
        item = entries.get((team, _name(player.get("name"))))
        if item is None:
            meta["status"] = "PLAYER_IMPACT_NOT_COVERED"; return out
        margin = finite(item.get("margin_points_if_available"))
        total = finite(item.get("total_points_if_available"))
        baseline = finite(item.get("historical_availability"))
        count = finite(item.get("sample_games"))
        cutoff = stamp(item.get("as_of_utc"))
        if (margin is None or total is None or baseline is None or count is None
                or not 0 <= baseline <= 1 or count < 30
                or abs(margin) > MAX_PLAYER_MARGIN or abs(total) > MAX_PLAYER_TOTAL
                or not cutoff or cutoff >= tip or not item.get("source_hash")):
            meta["status"] = "UNVERIFIED_PLAYER_IMPACT"; return out
        sign = 1 if side == "home" else -1
        m = sign * (probability - baseline) * margin
        t = (probability - baseline) * total
        delta_margin += m; delta_total += t
        variance_margin += probability * (1 - probability) * margin * margin
        variance_total += probability * (1 - probability) * total * total
        meta["players"].append({"side": side, "name": player["name"], "status": status,
                                "p_play": probability, "baseline_availability": baseline,
                                "margin_delta": round(m, 4), "total_delta": round(t, 4)})
    if abs(delta_margin) > 22 or abs(delta_total) > 28:
        meta.update(status="AGGREGATE_IMPACT_OUT_OF_BOUNDS", players=[])
        return out
    mu_m = base_margin + delta_margin; mu_t = base_total + delta_total
    sigma_m = math.sqrt(ms * ms + variance_margin)
    sigma_t = math.sqrt(ts * ts + variance_total)
    raw_home = normal_greater(mu_m, sigma_m, 0)
    cal = (pred.get("calibration") or {})
    p_home = isotonic(cal.get("moneyline_isotonic"), raw_home)
    p_over = isotonic(cal.get("total_over_225_5_isotonic"),
                      normal_greater(mu_t, sigma_t, 225.5))
    out.update(margin_mean_home_minus_away=mu_m, total_mean=mu_t,
               margin_sigma=sigma_m, total_sigma=sigma_t,
               moneyline_home_probability=p_home, moneyline_away_probability=1-p_home,
               moneyline_home_probability_raw=raw_home,
               total_over_225_5_probability=p_over,
               total_over_225_5_probability_raw=normal_greater(mu_t, sigma_t, 225.5))
    # Existing market lines stay fixed and must be recomputed after the mean shift.
    from nba_settlement_probabilities import settlement_probs
    out["markets"] = [dict(m) for m in pred.get("markets", [])]
    for m in out["markets"]:
        kind = m.get("market")
        line = finite(m.get("line"))
        if line is None or kind not in ("full_spread", "full_total"):
            continue
        mu, sigma = (mu_m, sigma_m) if kind == "full_spread" else (mu_t, sigma_t)
        p = normal_greater(mu, sigma, line)
        m.update(p_side1=p, p_side2=1-p, settlement=settlement_probs(line, mu, sigma))
    out["prediction_intervals"] = {
        "margin_home_minus_away": {k: {"low": mu_m-z*sigma_m, "high": mu_m+z*sigma_m} for k,z in Z.items()},
        "total": {k: {"low": mu_t-z*sigma_t, "high": mu_t+z*sigma_t} for k,z in Z.items()},
    }
    # Empirical intervals and baseline isotonic calibration have NOT been
    # revalidated after the player-impact change. Do not present them as such.
    out["empirical_prediction_intervals"] = {}
    out["moneyline_calibration_evidence"] = None
    meta.update(status="PLAYER_IMPACT_APPLIED_EXPERIMENTAL", adjusted=True,
                validation="POST_INJURY_PROBABILITY_NOT_RECALIBRATED",
                catalog_model_version=impact_catalog["model_version"],
                catalog_source_hash=impact_catalog["source_hash"],
                preinjury_home_probability=pred.get("moneyline_home_probability"),
                postinjury_home_probability=p_home,
                margin_delta=round(delta_margin, 4), total_delta=round(delta_total, 4))
    return out


def self_test():
    from copy import deepcopy
    pred = {"home": "ATL", "away": "MIA", "margin_mean_home_minus_away": 2.0,
            "total_mean": 226.0, "margin_sigma": 12.0, "total_sigma": 17.0,
            "moneyline_home_probability": .566, "markets": [
                {"market": "full_spread", "line": 3.5}, {"market": "full_total", "line": 225.5}]}
    inj = {"quality": "PUBLISHED_AFFECTED", "source_captured_at_utc": "2026-10-30T18:00:00Z",
           "home": {"report_state": "PUBLISHED", "players": [{"name": "Alpha, Test", "status": "Out"}]},
           "away": {"report_state": "PUBLISHED", "players": []}}
    catalog = {"schema_version": "nba-player-impact-v1", "captured_at_utc": "2026-10-30T16:00:00Z",
               "trained_through": "2026-10-01", "model_version": "validated-v1", "source_hash": "sha256:abc",
               "validation": {"status": "WALK_FORWARD_PASS", "test_games": 250},
               "players": [{"team": "ATL", "name": "Alpha, Test", "margin_points_if_available": 4,
                            "total_points_if_available": 2, "historical_availability": .9,
                            "sample_games": 60, "as_of_utc": "2026-10-01T00:00:00Z",
                            "source_hash": "sha256:player"}]}
    args = (pred, inj, "official NBA injury PDF", "2026-10-31T08:00:00+08:00")
    no = adjust(*args)
    assert not no["injury_adjustment"]["adjusted"]
    yes = adjust(*args, catalog)
    assert yes["injury_adjustment"]["adjusted"]
    assert yes["margin_mean_home_minus_away"] < pred["margin_mean_home_minus_away"]
    assert yes["total_mean"] < pred["total_mean"]
    assert yes["moneyline_home_probability"] < pred["moneyline_home_probability"]
    assert yes["markets"][0]["p_side1"] < normal_greater(2, 12, 3.5)
    assert adjust(*args[:-1], "2026-10-30T17:00:00Z", catalog)["injury_adjustment"]["status"] == "PENDING_OFFICIAL_INJURY"
    inj2 = deepcopy(inj); inj2["home"]["players"][0]["status"] = "Questionable"
    assert adjust(pred, inj2, args[2], args[3], catalog)["injury_adjustment"]["status"] == "UNCALIBRATED_AVAILABILITY_STATUS"
    print("NBA_INJURY_PROBABILITY_PIT_TEST_PASS")


if __name__ == "__main__":
    self_test()
