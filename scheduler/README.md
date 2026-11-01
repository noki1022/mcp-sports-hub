# External scheduler: independent Cloudflare Cron

This is a deployable **secondary trigger**, not an active installation until a Cloudflare account deploys it.

1. In Cloudflare Workers, create a Worker using `scheduler/worker.mjs`, or deploy from `scheduler/` with Wrangler.
2. Store `GITHUB_TOKEN` as a **Worker secret**, never in Git, with fine-grained GitHub **Actions: Read and Write** and **Contents: Read** permissions for `noki1022/mcp-sports-hub`. Do not expose it in logs or responses.
3. Apply the exact active-window UTC Cron Triggers from `wrangler.toml`; do not replace them with an every-minute trigger.
4. Verify scheduled invocation and GitHub workflow_dispatch in both providers' logs. The Worker does not run the NBA model; the existing GitHub workflows do.
5. Keep GitHub native cron as fallback. All times map into Asia/Shanghai; post-21:30 pregame monitoring is disabled, while the separate official-final settlement workflow remains. A git marker indicates API acceptance only, never device confirmation.

The external scheduler checks fixed slots 12:00, 14:00, 15:00, 18:00, 21:00 (+ recovery), priority 21:20, 21:30, 21:40 and 06:20, 06:30, 06:40. Automatic overnight hourly market monitoring (Beijing 22:30–05:30) is disabled. The Worker sleeps outside the active report, bounded-recovery and official-final settlement windows. It confirms an existing run/PushPlus marker before dispatch and does not rewrite match identities, model probabilities, or betting decisions.

**Limits:** Cloudflare Cron and GitHub dispatch still have queuing delays and outages. This is redundancy, not a hard real-time SLA; 21:30 analysis cannot be guaranteed on a phone at exactly 21:30. Review Worker failures and GitHub run success after first activation. For strict second-level SLA use a continuously running, monitored scheduler and a direct computation/notification path independent of GitHub Actions.
