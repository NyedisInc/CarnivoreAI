
'use strict';

const NEXT_RUNS_SHOWN = 3;
const LAST_RESULTS_SHOWN = 3;
const NAME_MAX = 28;

const AUTOMATIONS_ROUTE = '/api/v1/automations';
const SCHEDULER_ROUTE = '/api/v1/automations/scheduler';

const AUTOMATIONS_HASH = '#automations';

function clipName(name) {
  const text = String(name == null ? '' : name).trim();
  if (!text) return '(unnamed)';
  return text.length > NAME_MAX ? `${text.slice(0, NAME_MAX - 1)}...` : text;
}

function whenText(epochSeconds, nowMs, timeZone) {
  const date = new Date(epochSeconds * 1000);
  const zone = timeZone ? { timeZone } : {};
  const day = (d) => d.toLocaleDateString('en-US', { year: 'numeric', month: 'numeric', day: 'numeric', ...zone });
  const time = date.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', ...zone });
  if (day(date) === day(new Date(nowMs))) return time;
  return `${date.toLocaleDateString('en-US', { weekday: 'short', ...zone })} ${time}`;
}

function runStatusText(run) {
  const status = String((run && run.status) || 'unknown').replace(/_/g, ' ');
  if (run && run.status === 'skipped' && run.reason) return `${status}: ${String(run.reason).replace(/_/g, ' ')}`;
  return status;
}

function summarize(body) {
  const rows = body && Array.isArray(body.automations) ? body.automations : null;
  if (!rows) return { reachable: false, paused: false, total: 0, upcoming: [], recent: [] };

  const upcoming = rows
    .filter((a) => a && a.enabled && typeof a.next_fire_at === 'number')
    .map((a) => ({ name: clipName(a.name), at: a.next_fire_at }))
    .sort((a, b) => a.at - b.at)
    .slice(0, NEXT_RUNS_SHOWN);

  const recent = rows
    .filter((a) => a && a.last_run)
    .map((a) => {
      const run = a.last_run;
      const at = [run.ended_at, run.started_at, run.slot_at].find((v) => typeof v === 'number');
      return { name: clipName(a.name), status: runStatusText(run), at: typeof at === 'number' ? at : 0 };
    })
    .sort((a, b) => b.at - a.at)
    .slice(0, LAST_RESULTS_SHOWN);

  return {
    reachable: true,
    paused: Boolean(body.scheduler && body.scheduler.paused === true),
    total: rows.length,
    upcoming,
    recent,
  };
}

async function fetchAutomationsSnapshot(client) {
  const result = await client.getAuthed(AUTOMATIONS_ROUTE);
  return result.reachable ? summarize(result.data) : summarize(null);
}

async function setSchedulerPaused(client, paused) {
  const result = await client.sendAuthed(SCHEDULER_ROUTE, { paused: Boolean(paused) });
  return { ok: result.reachable, error: result.error };
}

module.exports = {
  AUTOMATIONS_HASH,
  AUTOMATIONS_ROUTE,
  SCHEDULER_ROUTE,
  NEXT_RUNS_SHOWN,
  LAST_RESULTS_SHOWN,
  summarize,
  fetchAutomationsSnapshot,
  setSchedulerPaused,
  whenText,
};
