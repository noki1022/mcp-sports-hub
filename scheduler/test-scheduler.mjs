import assert from "node:assert/strict";
import { CRONS, plannedJobs, dispatchAt } from "./worker.mjs";

const at = value => Date.parse(value);
const kinds = (date, cron) => plannedJobs(at(date), cron).map(x => x.kind);

assert.deepEqual(Object.keys(CRONS), ["REVIEW", "PREGAME", "FIXED", "REGRESSION"]);
assert.deepEqual(kinds("2026-10-30T04:00:00Z", CRONS.FIXED), ["full"]);
assert.deepEqual(kinds("2026-10-30T06:08:00Z", CRONS.FIXED), ["full"]);
assert.deepEqual(kinds("2026-10-30T07:28:00Z", CRONS.FIXED), ["full"]);
assert.deepEqual(kinds("2026-10-30T10:18:00Z", CRONS.FIXED), ["full"]);
assert.deepEqual(kinds("2026-10-30T13:16:00Z", CRONS.FIXED), ["full"]);

assert.deepEqual(kinds("2026-10-30T13:20:00Z", CRONS.FIXED), ["priority_2130", "health"]);
assert.deepEqual(kinds("2026-10-30T13:30:00Z", CRONS.FIXED), ["priority_2130"]);
assert.deepEqual(kinds("2026-10-30T13:40:00Z", CRONS.FIXED), ["priority_2130", "health"]);
assert.deepEqual(kinds("2026-10-30T13:55:00Z", CRONS.FIXED), ["health"]);

assert.deepEqual(kinds("2026-10-30T22:20:00Z", CRONS.PREGAME), ["priority_0630"]);
assert.deepEqual(kinds("2026-10-31T05:50:00Z", CRONS.PREGAME), ["priority_0630", "injury_watch"]);
assert.deepEqual(kinds("2026-10-31T05:55:00Z", CRONS.PREGAME), ["injury_watch"]);
assert.deepEqual(kinds("2026-10-30T22:35:00Z", CRONS.PREGAME), ["injury_watch", "health"]);
assert.deepEqual(kinds("2026-10-30T22:40:00Z", CRONS.PREGAME), ["priority_0630", "injury_watch", "health"]);
assert.deepEqual(kinds("2026-10-30T13:30:00Z", CRONS.PREGAME), ["injury_watch"]);
assert.deepEqual(kinds("2026-10-30T13:35:00Z", CRONS.PREGAME), []);
assert.deepEqual(kinds("2026-10-30T14:30:00Z", CRONS.PREGAME), []);
assert.equal(plannedJobs(at("2026-10-30T14:30:00Z")).some(x => x.kind === "hourly"), false);

assert.deepEqual(kinds("2026-10-30T14:30:00Z", CRONS.REVIEW), ["night_review"]);
assert.deepEqual(kinds("2026-10-30T22:45:00Z", CRONS.REVIEW), ["night_review"]);
assert.deepEqual(kinds("2026-10-30T08:01:00Z", CRONS.FIXED), ["odds_settlement"]);
assert.deepEqual(kinds("2026-10-30T20:01:00Z", CRONS.REGRESSION), ["offline_regression"]);
assert.equal(plannedJobs(at("2026-10-30T08:06:00Z"), CRONS.FIXED)[0].kind, "odds_settlement");
assert.deepEqual(kinds("2026-10-30T20:01:00Z", CRONS.FIXED), []);

const acceptedFixed = {
  async fetch(url) {
    if (url.includes("/contents/")) {
      return { status: 200, ok: true, json: async () => ({
        content: btoa(JSON.stringify({
          state: "API_ACCEPTED_NOT_DEVICE_CONFIRMED", slot: "1500"
        }))
      }) };
    }
    throw new Error("ACCEPTED_FIXED_REPORT_MUST_NOT_QUERY_OR_DISPATCH");
  }
};
const accepted = await dispatchAt(at("2026-10-30T07:00:00Z"), { GITHUB_TOKEN: "FAKE" }, acceptedFixed, CRONS.FIXED);
assert.equal(accepted.results[0].state, "API_ALREADY_ACCEPTED");

// A prior review marker for one date must not stop polling another delayed slate.
let reviewDispatch = false;
const reviewWithOlderMarker = {
  async fetch(url, options = {}) {
    if (url.includes("/runs?")) return { ok: true, json: async () => ({ workflow_runs: [] }) };
    if (url.endsWith("/dispatches")) {
      reviewDispatch = true;
      return { status: 204 };
    }
    throw new Error("UNEXPECTED_REVIEW_URL_" + url);
  }
};
const reviewResult = await dispatchAt(at("2026-10-30T14:30:00Z"), { GITHUB_TOKEN: "FAKE" }, reviewWithOlderMarker, CRONS.REVIEW);
assert.equal(reviewResult.results[0].state, "DISPATCH_ACCEPTED_NOT_COMPLETED");
assert.equal(reviewDispatch, true);

let posted = null;
const fixedFake = {
  async fetch(url, options = {}) {
    if (url.includes("/contents/")) return { status: 404, ok: false };
    if (url.includes("/runs?")) return { ok: true, json: async () => ({ workflow_runs: [] }) };
    if (url.endsWith("/dispatches")) {
      posted = JSON.parse(options.body);
      return { status: 204 };
    }
    throw new Error("UNEXPECTED_URL_" + url);
  }
};
const fixedResult = await dispatchAt(at("2026-10-30T07:00:00Z"), { GITHUB_TOKEN: "FAKE" }, fixedFake, CRONS.FIXED);
assert.equal(fixedResult.results[0].state, "DISPATCH_ACCEPTED_NOT_COMPLETED");
assert.equal(posted.inputs.report_slot, "1500");
assert.equal(posted.inputs.target_date, "2026-10-31");

const activeInjury = {
  async fetch(url) {
    if (url.includes("/runs?")) return {
      ok: true,
      json: async () => ({ workflow_runs: [{
        created_at: "2026-10-31T04:04:50Z",
        event: "workflow_dispatch",
        status: "in_progress",
        conclusion: null
      }] })
    };
    throw new Error("ACTIVE_INJURY_MUST_NOT_DISPATCH");
  }
};
const injuryResult = await dispatchAt(at("2026-10-31T04:05:00Z"), { GITHUB_TOKEN: "FAKE" }, activeInjury, CRONS.PREGAME);
assert.equal(injuryResult.results[0].state, "WORKFLOW_RUNNING");

const failedRun = {
  async fetch(url, options = {}) {
    if (url.includes("/contents/")) return { status: 404, ok: false };
    if (url.includes("/runs?")) return {
      ok: true,
      json: async () => ({ workflow_runs: [{
        created_at: "2026-10-30T07:00:10Z",
        event: "schedule",
        status: "completed",
        conclusion: "failure"
      }] })
    };
    if (url.endsWith("/dispatches")) return { status: 204 };
    throw new Error(url);
  }
};
const retry = await dispatchAt(at("2026-10-30T07:08:00Z"), { GITHUB_TOKEN: "FAKE" }, failedRun, CRONS.FIXED);
assert.equal(retry.results[0].state, "DISPATCH_ACCEPTED_NOT_COMPLETED");

const successfulRun = {
  async fetch(url) {
    if (url.includes("/contents/")) return { status: 404, ok: false };
    if (url.includes("/runs?")) return {
      ok: true,
      json: async () => ({ workflow_runs: [{
        created_at: "2026-10-30T07:00:10Z",
        event: "schedule",
        status: "completed",
        conclusion: "success"
      }] })
    };
    throw new Error("SUCCESSFUL_RUN_MUST_NOT_REDISPATCH");
  }
};
const noRetry = await dispatchAt(at("2026-10-30T07:08:00Z"), { GITHUB_TOKEN: "FAKE" }, successfulRun, CRONS.FIXED);
assert.equal(noRetry.results[0].state, "WORKFLOW_SUCCESS_WITHOUT_NEW_DISPATCH");

const unavailable = { async fetch() { return { ok: false, status: 503 }; } };
const failedClosed = await dispatchAt(at("2026-10-30T07:00:00Z"), { GITHUB_TOKEN: "FAKE" }, unavailable, CRONS.FIXED);
assert.equal(failedClosed.state, "PARTIAL_FAILURE");

console.log("CLOUDFLARE_PRIMARY_SCHEDULER_REGRESSION_PASS");
