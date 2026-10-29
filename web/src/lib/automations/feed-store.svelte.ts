import * as api from './api';
import { refusalText } from './format';
import { isLive } from './logic/words';
import type { FeedRun, ReportSlot } from './logic/types';

const CONCURRENCY = 4;
const FIRST_PAGE = 120;
const MORE_PAGE = 50;

export const feed = $state({
  runs: [] as FeedRun[],
  total: 0,
  nextBefore: null as string | null,
  status: 'idle' as 'idle' | 'loading' | 'ready' | 'error',
  error: '',
  loadingMore: false,
  unfiltered: null as FeedRun[] | null,
});

function noteUnfiltered(params: api.FeedParams): void {
  if (Object.keys(params).length === 0) feed.unfiltered = feed.runs;
}

export const reports = $state<Record<string, ReportSlot>>({});
export const boundary = $state<Record<string, FeedRun | null>>({});

const queued: string[] = [];
let active = 0;
let generation = 0;

export function lookup(runId: string): ReportSlot {
  return reports[runId] ?? { state: 'pending' };
}

function keep(run: FeedRun): void {
  if (isLive(run.status)) return;
  if (run.report_omitted || !('report' in run)) return;
  reports[run.run_id] = { state: 'ready', report: run.report ?? null };
}

function pump(): void {
  while (active < CONCURRENCY && queued.length) {
    const id = queued.shift()!;
    if (reports[id]) continue;
    active += 1;
    const mine = generation;
    api
      .getRun(id)
      .then((run) => {
        if (mine !== generation) return;
        if (isLive(run.status)) return;
        reports[id] = { state: 'ready', report: run.report ?? null };
      })
      .catch((error) => {
        if (mine === generation) reports[id] = { state: 'unreadable', reason: 'read_failed', message: refusalText(error) };
      })
      .finally(() => {
        active -= 1;
        pump();
      });
  }
}

export function ensureReport(runId: string): void {
  if (reports[runId] || queued.includes(runId)) return;
  queued.push(runId);
  pump();
}

function wantReports(runs: readonly FeedRun[]): void {
  for (const run of runs) if (run.has_report && !isLive(run.status) && !reports[run.run_id]) ensureReport(run.run_id);
}

export async function loadFeed(params: api.FeedParams): Promise<void> {
  generation += 1;
  feed.status = 'loading';
  try {
    const page = await api.listFeed({ ...params, limit: FIRST_PAGE, include_report: true });
    feed.runs = page.runs;
    noteUnfiltered(params);
    feed.total = page.total;
    feed.nextBefore = page.next_before;
    for (const run of page.runs) keep(run);
    wantReports(page.runs);
    feed.status = 'ready';
    feed.error = '';
  } catch (error) {
    feed.status = 'error';
    feed.error = refusalText(error);
  }
}

export async function loadOlder(params: api.FeedParams): Promise<void> {
  if (!feed.nextBefore || feed.loadingMore) return;
  feed.loadingMore = true;
  try {
    const page = await api.listFeed({ ...params, before: feed.nextBefore, limit: MORE_PAGE, include_report: true });
    const have = new Set(feed.runs.map((r) => r.run_id));
    feed.runs = [...feed.runs, ...page.runs.filter((r) => !have.has(r.run_id))];
    noteUnfiltered(params);
    feed.total = page.total;
    feed.nextBefore = page.next_before;
    for (const run of page.runs) keep(run);
    wantReports(page.runs);
  } catch (error) {
    feed.error = refusalText(error);
  } finally {
    feed.loadingMore = false;
  }
}

export async function refreshFeed(params: api.FeedParams): Promise<void> {
  if (feed.status !== 'ready') return;
  try {
    const page = await api.listFeed({ ...params, limit: FIRST_PAGE });
    const fresh = new Map(page.runs.map((r) => [r.run_id, r]));
    const oldest = page.runs.at(-1);
    const older = feed.runs.filter((r) => !fresh.has(r.run_id) && (!oldest || runOrder(r) < runOrder(oldest)));
    feed.runs = [...page.runs, ...older];
    noteUnfiltered(params);
    feed.total = page.total;
    if (!older.length) feed.nextBefore = page.next_before;
    wantReports(page.runs);
  } catch (error) {
    feed.error = refusalText(error);
  }
}

function runOrder(run: FeedRun): string {
  const at = run.ended_at ?? run.started_at ?? run.slot_at ?? run.created_at ?? 0;
  return `${String(Math.round(at * 1000)).padStart(16, '0')}:${run.run_id}`;
}

export async function loadBoundary(automationId: string, oldestRunId: string): Promise<FeedRun | null> {
  const key = `${automationId}:${oldestRunId}`;
  if (key in boundary) return boundary[key] ?? null;
  boundary[key] = null;
  try {
    const answer = await api.listRuns(automationId, 1, { before: oldestRunId, include_report: true });
    const run = (answer.runs[0] ?? null) as FeedRun | null;
    if (run) keep(run);
    boundary[key] = run;
    return run;
  } catch {
    return null;
  }
}
