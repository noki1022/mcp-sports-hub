# Basketball + football: exact-time dual scheduling (no compensation)

This directory controls the existing Cloudflare Worker `nba-external-schedule-watchdog`.
It does **not** execute 007 collection, inference, raw archiving, PushPlus delivery,
or settlement. Those jobs remain in GitHub Actions.

## Production policy (2026-11-06)

1. Both GitHub native cron and the same existing Cloudflare Worker cron fire at
   the **single canonical minute**. There are no delayed backup minutes,
   retry Cron triggers, resend workflows, or failure-driven compensatory sends.
2. Cloudflare may issue **one** workflow_dispatch at that exact timestamp.
   It inspects the canonical GitHub run and accepted/claimed marker first;
   if another run has already claimed that slot, it does not redispatch.
   Failure of that run **never** causes another dispatch.
3. GitHub's canonical run still has its normal runtime; queue latency and
   network/data availability are recorded as such. An original scheduled job
   executing after its trigger is **not** a second notification attempt.
4. NBA uses committed `reports/pushplus-sent` API acceptance markers;
   football uses immutable one-slot Release claim assets. Both are for
   **deduplication only**, never authorization to retry a failed send.
5. The existing delivery-health workflow is **manual, read-only**. It has no
   GitHub Actions write permission or PushPlus credentials and cannot dispatch.
6. The old standalone NBA schedule-fallback sender, auto-recovery script,
   manual compact resend workflow, and autonomous-recovery verification
   workflow were removed. Do not restore them under another name.
7. Original raw captures, independent pre-match evidence, 21:30 grading
   baselines, and official postgame settlement are separate from delivery
   remediation. Do not modify/erase old archived evidence.

## Beijing schedule

| Sport | Actual scheduled triggers |
| --- | --- |
| Basketball full reports | 12:00–21:00 hourly, plus 00:30 and 03:30 |
| Basketball priorities | 21:30 and 06:30 |
| Football analysis/push | 12:00–21:00 hourly |
| Football priorities | 21:30 and 06:30 |
| Football silent captures | 00:00–06:00 hourly |
| Basketball silent captures | 00:00–06:00 hourly |

The review of completed games is driven by verified official-FINAL evidence,
not by replaying a missed pre-match notification. Do not mistake a GitHub
workflow status of success, a Cloudflare dispatch 204, or a PushPlus API
acceptance for an iPhone delivery receipt.

## Worker Cron configuration

```toml
crons = ["0 4-13,16-22 * * *", "30 13,16,19,22 * * *"]
```

The two Cron expressions cover all canonical Cloudflare triggers, do not
exceed the Cloudflare Free limit of five, and have **zero noncanonical
recovery ticks**. GitHub scheduled tasks are enumerated in the corresponding
workflow YAML files and validated by `scripts/validate_nba_schedules.py`,
`scheduler/test-scheduler.mjs`, and the no-resend P0 gate.

## Deployment and verification

The existing GitHub-linked Cloudflare Workers Builds integration deploys
Worker code/config. A green GitHub check is build evidence, not proof of
a live Cron execution. Inspect deployed version, actual Cron Trigger list,
and Worker logs; match its one dispatch against GitHub canonical workflow run,
analysis artifact, archive, and PushPlus API acceptance marker. Escalate
a missing marker as a *failure to investigate*, **never as a reason to resend**.
