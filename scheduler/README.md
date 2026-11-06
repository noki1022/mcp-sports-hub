# Basketball and football — one 12-hour analysis window

**Beijing time (UTC+08):** 12:00, 13:00, 14:00, 15:00, 16:00, 17:00,
18:00, 19:00, 20:00, **21:00**, 22:00, 23:00. Exactly 12 scheduled
snapshots and reports per sport every calendar day. Midnight is the end of
the window; no 00:00 additional run, 21:30, 00:30, 03:30 or 06:30.

At 21:00 a SHA-verified prediction is locked as the **only** review/scoring
source. The later 22:00 and 23:00 snapshots are archived for historical
model research, but cannot overwrite or substitute the 21:00 answer.
If 21:00 is missing, the official scorecard is **missing**, not backfilled
with a different slot.

## Two independent sporting-day rules

* **Football:** On Friday, capture and analyse only the 007 official sale
  identifiers `周五001`, `周五002`, etc., even if those games kick off
  after midnight on Saturday. Exclude any `周六nnn` entries. On Saturday,
  the equivalent `周六nnn` group is the day's slate. The full 007 raw
  response is archived unchanged and only the **derived model fixtures**
  are filtered. Review those originally frozen exact match IDs after
  independently verified full-time scores are available.
* **Basketball:** Continue the next Beijing game display date convention
  used by 007/NBA; keep the original 12:00 cohort. The 21:00 report for
  that date is the only five-market outcome-scoring baseline.

GitHub scheduled workflows and the existing Cloudflare Worker both have
an original 12:00–23:00 exact-hour trigger for the same processing pipeline.
Cloudflare does not analyse/send directly and neither scheduler performs
late compensation or a second send. Deduplication claims stay in force.
A GitHub workflow success or a Cloudflare dispatch 204 never proves the
message arrived on the recipient's iPhone.

Worker cron configuration (UTC):

```toml
crons = ["0 4-15 * * *"]
```

Keep result verification and archival workflows separate from live odds
capture. Official result settlement may occur after midnight, but it
must read an already sealed 21:00 forecast; it cannot perform another
pregame market capture or rewrite historical predictions.

Never remove raw captured 007 bytes, original prediction snapshots,
timestamps, or append-only result evidence when pruning old schedules.

Regression checks: `node scheduler/test-scheduler.mjs`,
`python scripts/validate_nba_schedules.py`,
`python -m unittest discover -s tests -p test_football_007_live_capture.py`,
and the 21:00 frozen-final tests.
