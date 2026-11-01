# Cloudflare primary scheduler

Cloudflare Workers is the primary clock for the NBA/007 automation. The Worker dispatches the existing GitHub Actions workflows; it does not run the model, change odds, alter match identities, or make betting decisions.

## Active schedule

All Cloudflare Cron expressions are UTC. The Worker converts each event to Asia/Shanghai before selecting a job.

- Fixed 007 capture and five-market reports: Beijing 12:00, 14:00, 15:00, 18:00 and 21:00, with the existing bounded retry points.
- Final pre-cutoff report: 21:20 / 21:30 / 21:40, with the existing 21:58 cutoff gate.
- Morning report: every ten minutes from 06:20 through 13:50 while the immutable 21:30 cohort still has a safely pre-tip game.
- Official injury change watch: every five minutes from 06:30 through 21:30.
- Delivery recovery checks: the existing fixed report and priority recovery windows.
- Official-final settlement: every fifteen minutes, including overnight, until the last frozen game is officially Final. This is not odds/market monitoring.
- Ancillary daily audits: odds settlement failover at 16:01 and offline full-chain regression at 04:01 Beijing (with bounded retries).

Automatic overnight hourly market capture/analysis after 21:30 remains disabled. The manually triggered titan007-final-hourly workflow remains available for deliberate diagnostics only.

## Cloudflare triggers

wrangler.toml defines four Cron Triggers:
1. Every fifteen minutes — official-final settlement checks only.
2. Every five minutes during the pregame window — injury watch, morning retries and morning delivery recovery.
3. Bounded fixed-time trigger — scheduled reports, evening priority and delivery recovery, plus the 16:00 odds settlement failover.
4. Dedicated 04:00 Beijing trigger — offline full-chain regression only.

This uses four triggers, leaving headroom under the current Cloudflare Free account limit of five Cron Triggers. The Worker does not wake for the removed 22:30–05:30 hourly market-monitoring schedule.

## Required GitHub repository secrets

Add these under Settings → Secrets and variables → Actions. Never paste tokens into chat or commit them to the repository.

- CLOUDFLARE_API_TOKEN: Cloudflare API token allowed to edit Workers Scripts for the target account.
- CLOUDFLARE_ACCOUNT_ID: Cloudflare account ID.
- CLOUDFLARE_SCHEDULER_GITHUB_TOKEN: fine-grained GitHub PAT for noki1022/mcp-sports-hub with Actions: Read and write and Contents: Read.

The deployment workflow deploy-cloudflare-primary-scheduler.yml deploys the Worker and stores the GitHub PAT as the Worker secret GITHUB_TOKEN. The PAT is never written to Git or printed in logs. The deploy workflow is manual or runs when scheduler files are pushed to main; if required secrets are absent, it reports that deployment is pending and exits without disrupting GitHub fallback schedules.

## Safe rollout

GitHub native Cron schedules remain enabled as a fail-safe until Cloudflare is deployed and verified. The Worker checks accepted PushPlus markers and current workflow runs before dispatching, while each production workflow retains its own concurrency and fail-closed gates. This prevents a scheduler migration from creating a second model/push pipeline.

After Cloudflare deployment succeeds:
1. Confirm the Worker has all three Cron Triggers in Cloudflare.
2. Confirm CLOUDFLARE_PRIMARY_SCHEDULER logs and the matching GitHub workflow_dispatch runs.
3. Keep both clocks for an observation period; do not remove the GitHub fallback until Cloudflare runs and PushPlus API-acceptance markers are verified.

A PushPlus marker means the API accepted the message, not that the phone displayed it. GitHub workflow success alone is not proof of push delivery.

Cloudflare Cron changes can take up to 15 minutes to propagate. Cron and GitHub dispatch can be delayed or unavailable; this is resilient orchestration, not a hard real-time SLA.
