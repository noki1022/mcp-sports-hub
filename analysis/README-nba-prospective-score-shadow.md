# Genuine pretip research NBA score-only shadow

The most important check on historical-model accuracy is a prediction frozen **before** NBA tipoff. This workflow makes immutable GitHub Actions artifacts containing model version hashes, precise capture time, ESPN event ID, official ET/Beijing fixture times, home/away teams, score-only predicted margin and total, home-win probability, and latest source-game date.

## Integrity guarantees

- All training scores come from the validated 23,574 historical games, 675 new 2025–26 score finals, and independently completed/ESPN-crosschecked 2026–27 games. No unsupported or mismatching future final enters the as-of source.
- Future games come from the ESPN live schedule only and must start at least 10 minutes after actual forecast capture time. Strictly match known NBA teams and source event IDs.
- Future opponent features use a dedicated **scoreless fixture** extension. No synthetic future outcome is ever created to calculate a future game's feature vector.
- Model ridge weights use completed historical games only. Same-day game scores do not influence other game predictions. The model is a research-only challenger, separate from existing production models and market odds.
- All forecast records include capture and tipoff timestamps, model/source code SHA-256, dataset hashes and full input checks. A pinned 60-day artifact can later be scored against independently fetched finals, not silently overwritten.
- Fixed training-residual Gaussian probability dispersion is not an independently established calibration. No prediction is an authorized live betting signal. Historical 007 and bookmaker side-price orientation assumptions are entirely absent here.
- No schedule or push changes are made. The workflow only runs on PR changes and manual workflow dispatch. It does not alter live automation, cloud schedulers, 007 ID3 Crown, Jingcai or PushPlus.

## Reproduce

    python3 analysis/nba_prospective_score_shadow.py --selftest
    python3 analysis/nba_prospective_score_shadow.py --out /tmp/nba-prospective-score-shadow

Produced files: manifest.json and frozen_pregame_score_only.jsonl, stored in GitHub Actions artifact for 60 days.

**Important:** A historical refit can be audited, but it cannot be represented as an untouched prospective forecast. Only the actual before-tip workflow artifact's captured_at and SHA-provenance qualify.
