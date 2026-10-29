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

const REPORT_CACHE_MAX = 600;
const queued: string[] = [];
let active = 0;
let generation = 0;

export function trimReports(): void {
  const keys = Object.keys(reports);
  if (keys.length <= REPORT_CACHE_MAX) return;
  const loaded = new Set(feed.runs.map((r) => r.run_id));
  const order = [...keys.filter((k) => !loaded.has(k)), ...keys.filter((k) => loaded.has(k))];
  for (const k of order.slice(0, keys.length - REPORT_CACHE_MAX)) delete reports[k];
  const kept = Object.keys(boundary);
  if (kept.length > REPORT_CACHE_MAX) for (const k of kept.slice(0, kept.length - REPORT_CACHE_MAX)) delete boundary[k];
}

export function releaseFeedCaches(): void {
  generation += 1;
  queued.length = 0;
  for (const k of Object.keys(reports)) delete reports[k];
  for (const k of Object.keys(boundary)) delete boundary[k];
  feed.runs = [];
  feed.total = 0;
  feed.nextBefore = null;
  feed.status = 'idle';
  feed.error = '';
  feed.loadingMore = false;
  feed.unfiltered = null;
}

export function lookup(runId: string): ReportSlot {
  return reports[runId] ?? { state: 'pending' };
}

export interface ReportCarrier {
  run_id: string;
  status: string;
  has_report?: boolean;
  report?: unknown;
  report_omitted?: boolean;
}

export function keepReport(run: ReportCarrier, queueOmitted = false): void {
  if (!run.has_report || isLive(run.status) || reports[run.run_id]) return;
  if (run.report_omitted || !('report' in run)) {
    if (queueOmitted) ensureReport(run.run_id);
    return;
  }
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
  const mine = ++generation;
  feed.status = 'loading';
  try {
    const page = await api.listFeed({ ...params, limit: FIRST_PAGE, include_report: true });
    if (mine !== generation) return;
    feed.runs = page.runs;
    noteUnfiltered(params);
    feed.total = page.total;
    feed.nextBefore = page.next_before;
    for (const run of page.runs) keepReport(run);
    trimReports();
    wantReports(page.runs);
    feed.status = 'ready';
    feed.error = '';
  } catch (error) {
    if (mine !== generation) return;
    feed.status = 'error';
    feed.error = refusalText(error);
  }
}

export async function loadOlder(params: api.FeedParams): Promise<void> {
  if (!feed.nextBefore || feed.loadingMore) return;
  feed.loadingMore = true;
  const mine = generation;
  try {
    const page = await api.listFeed({ ...params, before: feed.nextBefore, limit: MORE_PAGE, include_report: true });
    if (mine !== generation) return;
    const have = new Set(feed.runs.map((r) => r.run_id));
    feed.runs = [...feed.runs, ...page.runs.filter((r) => !have.has(r.run_id))];
    noteUnfiltered(params);
    feed.total = page.total;
    feed.nextBefore = page.next_before;
    for (const run of page.runs) keepReport(run);
    wantReports(page.runs);
  } catch (error) {
    if (mine === generation) feed.error = refusalText(error);
  } finally {
    feed.loadingMore = false;
  }
}

export async function refreshFeed(params: api.FeedParams): Promise<void> {
  if (feed.status !== 'ready') return;
  const mine = generation;
  try {
    const page = await api.listFeed({ ...params, limit: FIRST_PAGE });
    if (mine !== generation) return;
    const fresh = new Map(page.runs.map((r) => [r.run_id, r]));
    const oldest = page.runs.at(-1);
    const older = feed.runs.filter((r) => !fresh.has(r.run_id) && (!oldest || runOrder(r) < runOrder(oldest)));
    feed.runs = [...page.runs, ...older];
    noteUnfiltered(params);
    feed.total = page.total;
    if (!older.length) feed.nextBefore = page.next_before;
    wantReports(page.runs);
  } catch (error) {
    if (mine === generation) feed.error = refusalText(error);
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
    if (run) keepReport(run);
    boundary[key] = run;
    return run;
  } catch {
    return null;
  }
}
