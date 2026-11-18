# Basketball and football — one 12-hour analysis window

**Beijing time (UTC+08):** 12:00, 13:00, 14:00, 15:00, 16:00, 17:00,
18:00, 19:00, 20:00, **21:00**, 22:00, 23:00. Exactly 12 scheduled
snapshots and reports per sport every calendar day. Midnight is the end of
the window; no 00:00 additional run, 21:30, 00:30, 03:30 or 06:30.

For NBA, at 21:00 a SHA-verified prediction is locked as the **only** review/scoring
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

The existing Cloudflare Worker prepares each original hourly GitHub job
30 minutes early. It prepares the 13:00 football review at 12:30, and the
NBA official-final checks 10 minutes before their original :25/:50 ticks.
Only checkout, Python/dependency setup and bounded waiting happen early.
Actual collection and result reads start at the original slot. Real source
timestamps are never replaced with a scheduled timestamp.

The runner verifies that its dispatch was created during the original
preparation minute (120-second provider allowance), on main, first attempt,
for the matching canonical route/date/slot. It waits until the target time
before releasing business steps. Expired preparations cannot compensate.

Native GitHub triggers remain. Before business work they query for the
prepared original. Its existence owns the slot even if failed or cancelled;
they exit rather than retry it. If no preparation was created, the original
native trigger retains its existing behavior. Immutable send claims remain
the final atomic fence. The Worker no longer redispatches those senders at
the business minute in preparation mode. There is no delayed fallback.

Football capture, immutable Release archive, claim and send now execute
sequentially on the same runner. Raw failure bytes are still archived after
analysis failure; unsuccessful analysis or archive blocks the sender. Push
credentials remain confined to the claim/preflight and sending steps.

Shared per-match finalization and verified-result archive workflows retain
their existing original cron and workflow-run triggers. Their archive-only
downstream jobs may still queue; they do not create an additional sender.

This uses public-repository standard GitHub runners and the existing free
Worker only. No Cloudflare Container, Workers Paid upgrade, new credential,
VM, trial-credit service or paid runner is provisioned. Four cron expressions
fit the Workers Free limit of five per account (including other Workers).
Preparation reduces queue exposure; it is not a promise of exact delivery
when GitHub delays longer than the preparation lead or a provider is down.
A GitHub workflow success or a Cloudflare dispatch 204 never proves the
message arrived on the recipient's iPhone.

Worker cron configuration (UTC):

```toml
crons = ["0 4-15 * * *", "25,50 * * * *", "30 3-14 * * *", "15,40 * * * *"]
[vars]
GITHUB_PREWARM = "1"
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
