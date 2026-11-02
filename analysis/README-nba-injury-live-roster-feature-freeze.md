# Existing NBA injury shadow: real future official injury + current roster + prior minutes

## Why this exists

Current injury shadow already runs in production (21:30/06:30), but initially 11 immutable pretip captures had **zero** eligible paired injury-adjusted probabilities. PR #218 found 39/60 historic official injury names with stable historic player IDs and prior minutes; PR #219 independently collected current rosters (28 NBA teams, 485 entries, 396 ID+team+minute matches), but a roster newly captured in November cannot retroactively alter old predictions. This job unites the **same live future** NBA official injury PDF, ESPN schedule, current ESPN rosters, and pregame historic player minutes in a separate frozen research artifact.

## Source and chronology gates

1. Read genuinely future ESPN NBA fixtures and their real UTC + Beijing tipoffs; reject contests closer than 10 minutes, completed games, unknown franchises or duplicated events.
2. Discover the NBA official injury PDF from the official listing, preserving actual fetch timestamp, document hash, report date and unparsed names; never invent another PDF URL or treat “not submitted” as “healthy.” If a report is unavailable the collector fails closed.
3. Fetch same-run ESPN roster snapshots for up to 30 teams, record per-roster hash, source URL and actual UTC capture. ESPN athlete ID and NBA player-log person ID are **different namespaces**.
4. Obtain 2024–2026 player-game logs with the existing bounded reader; build prior-minute identities strictly from games dated **before** the current Eastern calendar day.
5. For each official injury-listed athlete, require a unique normalized official name ↔ current roster team ↔ historical NBA player ID, at least 3 *earlier same-team* games, and both report/roster snapshots captured before the matchup tip. Reject ambiguous/transfer/current-day minutes.
6. Export observed status-specific prior-minute *exposure* only, not point deductions or calibrated player value; no false injury win probability is generated. A fully matched game still requires model coefficients validated on independent later games before any production application.

## Scope and verification

Run (CI PR only or manual dispatch; **no new cron**):

    python3 analysis/nba_injury_live_roster_feature_freeze.py --selftest
    python3 analysis/nba_injury_live_roster_feature_freeze.py --out /tmp/nba-live-injury-roster-frozen

Outputs: `prospective_official_injury_roster_minutes.jsonl` and `audit.json` with hash manifest, source URLs and collection clocks.

**Cannot claim improved prediction accuracy** until the already-running injury shadow has a real frozen compatible candidate model and sufficient new paired games. No modified original models, no new active injury model, no writes to 007/ID3 Crown/Jingcai, no Cloudflare/GitHub schedule changes, and no PushPlus changes.

The source PDF release time is not independently verified; collection time is the only independently observed as-of proof. Genuine opening/closing market timestamps and ROI are not inferred.
