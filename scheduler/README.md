# Cloudflare Workers Builds — NBA secondary scheduler

The existing Cloudflare Worker **nba-external-schedule-watchdog** is already
linked to this GitHub repository through **Cloudflare Workers Builds**. GitHub
commit checks dated Nov 1–2, 2026 show successful Cloudflare production builds,
including the Nov 2 merge of PR #202 (Cloudflare production version ID
`191d4403-54a8-44c2-aafa-3ba5f42cf65a`). This is evidence of the
existing production build integration, NOT a live Cron execution log.

The older one-off GitHub Actions workflow called "Deploy Cloudflare primary NBA
scheduler" reported missing credentials and skipped its own Wrangler steps.
That does **not** mean the independent Cloudflare Workers Builds integration
failed or that the existing Worker needs redeployment through a second system.
Do not create or request another Worker or GitHub Actions deployment route.

## Architecture

- **Cloudflare Cron**: independent, best-effort trigger, backed by
  `scheduler/worker.mjs` and `scheduler/wrangler.toml`.
- **GitHub Actions**: only executor of 007 collection, model analysis,
  report creation and PushPlus API sending.
- **Shared accepted marker**: both trigger paths check the GitHub
  `reports/pushplus-sent/YYYY-MM-DD/<slot>.json` ledger. The Worker also
  checks running/completed GitHub workflow state to avoid duplicate dispatch.
- **No direct Cloudflare PushPlus**: dispatch HTTP 204 means GitHub accepted
  a workflow request, not that the analysis ran or an iPhone received a push.

The Cloudflare schedule includes the normal daytime fixed slots, priority
21:30/06:30, the 22:00 official-final review recovery, and precisely two
overnight full-report exceptions: **00:30** and **03:30 Beijing time**.
Each new slot has Cloudflare backup checks at :30, :40 and :50. The old
Beijing 22:30–05:30 *hourly odds-monitoring* chain remains disabled.

## Verify production synchronization after a merge

1. Open Cloudflare dashboard > Workers & Pages >
   `nba-external-schedule-watchdog` > Deployments/Builds. Confirm the new
   `main` commit was built **and deployed to production**. This repository
   already has the Cloudflare Workers Builds GitHub integration; a separate
   GitHub Actions deployment workflow is neither needed nor wanted.
2. In the same Worker, inspect **Triggers > Cron Triggers**. Confirm exact
   expression `30,40,50 16,19 * * *` exists alongside existing triggers.
   Merely seeing it in Git does not prove Cloudflare applied it.
3. Inspect Cloudflare Worker **Logs/Observability** for actual Cron
   invocations at Beijing 00:30/00:40/00:50, 03:30/03:40/03:50.
   Look for `NBA_EXTERNAL_SCHEDULE`, `WORKFLOW_RUNNING`,
   `API_ALREADY_ACCEPTED`, or `DISPATCH_ACCEPTED_NOT_COMPLETED`,
   and investigate `NBA_EXTERNAL_SCHEDULE_FAILED`.
4. Correlate with GitHub Actions full-board run records for the same
   Beijing slot. A `workflow_dispatch` event alone does not prove Cloudflare
   originated it; the Cloudflare Worker invocation log is the independent
   origin evidence.
5. Validate API-accepted PushPlus markers for both slots and confirm that
   only one per-slot full report was sent. An accepted marker proves PushPlus
   server acceptance, not handset receipt.

If the live Cloudflare Cron set differs from `wrangler.toml`, investigate
the existing Workers Builds build/deploy configuration and its active root/
config. **Do not** silently build a second Worker or replace the existing
integration. There is no known Cloudflare API connector in this session,
so live Worker Cron and logs must not be claimed verified from GitHub alone.

This secondary scheduler cannot guarantee exact-second timing: even after
Cloudflare Cron fires promptly, the triggered GitHub Actions job may queue.
All Beijing dates are Asia/Shanghai; a started game or expired analysis
window must not receive a stale pre-tip full-board prediction.
