/**
 * Cloudflare is the primary clock for the NBA/007 automation.
 * GitHub Actions remains the execution engine and native Cron remains a
 * fail-safe during rollout. This Worker only dispatches existing workflows.
 *
 * Required Worker secret: GITHUB_TOKEN
 * Fine-grained GitHub token: Actions (read/write), Contents (read) on this repo.
 */
const OWNER = "noki1022";
const REPO = "mcp-sports-hub";
const BASE = "https://api.github.com/repos/" + OWNER + "/" + REPO;
const DAY_MS = 86400000;
const MINUTE_MS = 60000;
const ACCEPTED = "API_ACCEPTED_NOT_DEVICE_CONFIRMED";
const ACTIVE = new Set(["queued", "in_progress", "pending", "waiting", "requested"]);

export const CRONS = {
  REVIEW: "*/15 * * * *",
  PREGAME: "*/5 22-23,0-13 * * *",
  FIXED: "0,5,7,8,10,16,18,20,28,30,35,40,45,50,55 0-8,10,13,20,22-23 * * *"
};

const FIXED = [
  { hour: 12, slot: "1200", attempts: [0, 8, 18, 28] },
  { hour: 14, slot: "1400", attempts: [0, 8, 18, 28] },
  { hour: 15, slot: "1500", attempts: [0, 8, 18, 28] },
  { hour: 18, slot: "1800", attempts: [0, 8, 18, 28] },
  { hour: 21, slot: "2100", attempts: [0, 7, 16] }
];

const HEALTH_FIXED = [
  [12, 40, "1200", "tomorrow"],
  [14, 40, "1400", "tomorrow"],
  [15, 40, "1500", "tomorrow"],
  [18, 40, "1800", "tomorrow"],
  [21, 20, "2100", "tomorrow"],
  [21, 40, "2100", "tomorrow"],
  [21, 35, "2130", "tomorrow"],
  [21, 45, "2130", "tomorrow"],
  [21, 50, "2130", "tomorrow"],
  [21, 55, "2130", "tomorrow"]
];

function job(workflow, kind, slot, targetDate, local, startHour, startMinute, extra = {}) {
  return {
    workflow, kind, slot, target_date: targetDate, date: local.day,
    start_hour: startHour, start_minute: startMinute, ...extra
  };
}

export function beijingClock(timestamp) {
  const shifted = new Date(timestamp + 8 * 3600000);
  const day = shifted.toISOString().slice(0, 10);
  const tomorrow = new Date(shifted.getTime() + DAY_MS).toISOString().slice(0, 10);
  return { day, tomorrow, hour: shifted.getUTCHours(), minute: shifted.getUTCMinutes() };
}

export function plannedJobs(timestamp, cron = null) {
  const x = beijingClock(timestamp);
  const h = x.hour, m = x.minute, jobs = [];
  const all = cron === null;
  const fixedClock = all || cron === CRONS.FIXED;
  const pregameClock = all || cron === CRONS.PREGAME;
  const reviewClock = all || cron === CRONS.REVIEW;

  if (fixedClock) {
    for (const f of FIXED) {
      if (h === f.hour && f.attempts.includes(m)) {
        jobs.push(job("titan007-three-analysis.yml", "full", f.slot, x.tomorrow, x, f.hour, 0));
      }
    }
    if (h === 21 && [20, 30, 40].includes(m)) {
      jobs.push(job("nba-priority-2130.yml", "priority_2130", "2130", x.tomorrow, x, 21, 20));
    }
    for (const [hour, minute, slot, dateKind] of HEALTH_FIXED) {
      if (h === hour && m === minute) {
        jobs.push(job(
          "nba-delivery-health-watchdog.yml", "health", slot,
          dateKind === "tomorrow" ? x.tomorrow : x.day, x, h, m
        ));
      }
    }
    if (h === 16 && [0, 5, 10].includes(m)) {
      jobs.push(job("odds-results-settlement.yml", "odds_settlement", "1600", x.day, x, 16, 0));
    }
    if (h === 4 && [0, 5, 10].includes(m)) {
      jobs.push(job("nba-full-chain-e2e.yml", "offline_regression", "0400", x.day, x, 4, 0));
    }
  }

  if (pregameClock) {
    // Retry the morning report every ten minutes while the immutable 21:30
    // cohort still has a safely pre-tip game.
    const minuteOfDay = h * 60 + m;
    if (minuteOfDay >= 380 && minuteOfDay <= 830 &&
        (minuteOfDay - 380) % 10 === 0) {
      jobs.push(job("nba-priority-0630.yml", "priority_0630", "0630", x.day, x, 6, 20));
    }

    // Official injury watch: 06:30–21:30 Beijing, every five minutes.
    const inInjuryWindow =
      (h > 6 || (h === 6 && m >= 30)) &&
      (h < 21 || (h === 21 && m <= 30));
    if (inInjuryWindow && m % 5 === 0) {
      jobs.push(job(
        "nba-injury-change-watch.yml", "injury_watch", null, x.day, x, h, m,
        { blockAnyActive: true, activeWindowMs: 20 * MINUTE_MS }
      ));
    }

    // Existing morning delivery-recovery checks; the workflow applies the
    // immutable official-slate and safe pre-tip gates.
    if (h === 6 && [35, 40, 45, 50, 55].includes(m)) {
      jobs.push(job("nba-delivery-health-watchdog.yml", "health", "0630", x.day, x, h, m));
    }
  }

  if (reviewClock && m % 15 === 0) {
    // Official-final settlement only; this is not overnight odds monitoring.
    jobs.push(job(
      "nba-two-market-nightly-2200.yml", "night_review", "2200", x.day, x, h, m,
      { blockAnyActive: true, activeWindowMs: 20 * MINUTE_MS }
    ));
  }
  return jobs;
}

export function plannedJob(timestamp) {
  return plannedJobs(timestamp)[0] || null;
}

function slotStartEpoch(item) {
  const [year, month, day] = item.date.split("-").map(Number);
  return Date.UTC(year, month - 1, day, item.start_hour - 8, item.start_minute);
}

function ghHeaders(env) {
  if (!env.GITHUB_TOKEN) throw new Error("GITHUB_TOKEN_NOT_CONFIGURED");
  return {
    "Accept": "application/vnd.github+json",
    "Authorization": "Bearer " + env.GITHUB_TOKEN,
    "X-GitHub-Api-Version": "2022-11-28",
    "User-Agent": "nba-cloudflare-primary-scheduler/2.0"
  };
}

async function getJson(url, env, fetcher) {
  const response = await fetcher(url, { headers: ghHeaders(env) });
  if (!response.ok) throw new Error("GITHUB_READ_HTTP_" + response.status);
  return response.json();
}

async function markerAccepted(item, env, fetcher) {
  let path;
  if (item.kind === "night_review") return false;
  if (["full", "priority_2130", "priority_0630"].includes(item.kind)) {
    path = "reports/pushplus-sent/" + item.target_date + "/" + item.slot + ".json";
  } else {
    return false;
  }

  const response = await fetcher(BASE + "/contents/" + path + "?ref=main", {
    headers: ghHeaders(env)
  });
  if (response.status === 404) return false;
  if (!response.ok) throw new Error("MARKER_READ_HTTP_" + response.status);

  const file = await response.json();
  if (typeof file.content !== "string") throw new Error("MARKER_CONTENT_MISSING");
  const binary = atob(file.content.replace(/\s/g, ""));
  const bytes = Uint8Array.from(binary, c => c.charCodeAt(0));
  let body;
  try {
    body = JSON.parse(new TextDecoder().decode(bytes));
  } catch {
    throw new Error("BAD_MARKER_JSON");
  }
  if (body.state !== ACCEPTED) return false;
  return item.kind === "night_review" || body.slot === item.slot;
}

function runWindowStart(item, timestamp) {
  if (["full", "priority_2130", "priority_0630", "odds_settlement", "offline_regression"].includes(item.kind)) {
    return slotStartEpoch(item) - 2 * MINUTE_MS;
  }
  return timestamp - 2 * MINUTE_MS;
}

async function dispatchOne(item, timestamp, env, fetcher) {
  if (await markerAccepted(item, env, fetcher)) {
    return { state: "API_ALREADY_ACCEPTED", kind: item.kind, slot: item.slot };
  }

  const uri = BASE + "/actions/workflows/" + encodeURIComponent(item.workflow) +
    "/runs?per_page=30&branch=main";
  const data = await getJson(uri, env, fetcher);
  const runs = data.workflow_runs || [];
  const lower = runWindowStart(item, timestamp), upper = timestamp + 2 * MINUTE_MS;

  const relevant = runs.filter(run => {
    if (!["workflow_dispatch", "schedule"].includes(run.event)) return false;
    const when = Date.parse(run.created_at);
    return Number.isFinite(when) && when >= lower && when <= upper;
  });

  if (item.blockAnyActive) {
    const activeSince = timestamp - (item.activeWindowMs || 20 * MINUTE_MS);
    const active = runs.some(run => {
      if (!ACTIVE.has(run.status)) return false;
      const when = Date.parse(run.created_at);
      return Number.isFinite(when) && when >= activeSince;
    });
    if (active) return { state: "WORKFLOW_RUNNING", kind: item.kind, slot: item.slot };
  }

  if (relevant.some(run => ACTIVE.has(run.status))) {
    return { state: "WORKFLOW_RUNNING", kind: item.kind, slot: item.slot };
  }
  if (relevant.some(run => run.conclusion === "success")) {
    return { state: "WORKFLOW_SUCCESS_WITHOUT_NEW_DISPATCH", kind: item.kind, slot: item.slot };
  }

  const body = { ref: "main" };
  if (item.kind === "full") {
    body.inputs = { target_date: item.target_date, report_slot: item.slot };
  } else if (item.kind === "health") {
    body.inputs = { slot: item.slot, target_date: item.target_date };
  }

  const response = await fetcher(
    BASE + "/actions/workflows/" + encodeURIComponent(item.workflow) + "/dispatches",
    {
      method: "POST",
      headers: { ...ghHeaders(env), "Content-Type": "application/json" },
      body: JSON.stringify(body)
    }
  );
  if (response.status !== 204) throw new Error("GITHUB_DISPATCH_HTTP_" + response.status);

  return {
    state: "DISPATCH_ACCEPTED_NOT_COMPLETED",
    kind: item.kind, slot: item.slot, target_date: item.target_date, workflow: item.workflow
  };
}

export async function dispatchAt(timestamp, env, fetcher = fetch, cron = null) {
  const jobs = plannedJobs(timestamp, cron);
  if (!jobs.length) return { state: "NO_SLOT", results: [], failures: [] };

  const settled = await Promise.allSettled(
    jobs.map(item => dispatchOne(item, timestamp, env, fetcher))
  );
  const results = settled.map((entry, index) => entry.status === "fulfilled"
    ? entry.value
    : { state: "DISPATCH_ERROR", kind: jobs[index].kind, slot: jobs[index].slot, error: String(entry.reason) });
  const failures = results.filter(result => result.state === "DISPATCH_ERROR");
  return { state: failures.length ? "PARTIAL_FAILURE" : "PROCESSED", results, failures };
}

export default {
  async scheduled(controller, env) {
    const scheduledAt = Number(controller.scheduledTime || Date.now());
    if (Date.now() - scheduledAt > 5 * MINUTE_MS) {
      console.error("CLOUDFLARE_SCHEDULE_TICK_STALE", new Date(scheduledAt).toISOString());
      return;
    }
    try {
      const result = await dispatchAt(scheduledAt, env, fetch, controller.cron || null);
      if (result.state !== "NO_SLOT") console.log("CLOUDFLARE_PRIMARY_SCHEDULER", JSON.stringify(result));
      if (result.failures.length) throw new Error("SCHEDULER_PARTIAL_FAILURE_" + result.failures.length);
    } catch (error) {
      console.error("CLOUDFLARE_PRIMARY_SCHEDULER_FAILED", String(error));
      throw error;
    }
  },
  async fetch() {
    return new Response("Not Found", { status: 404 });
  }
};
