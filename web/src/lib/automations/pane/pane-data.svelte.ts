import * as api from '../api';
import { ensureReport, keepReport, lookup, reports } from '../feed-store.svelte';
import { slotOf, type FeedRow } from '../logic/feed';
import type { ReportSlot, RunRow } from '../logic/types';
import { isLive, runTime } from '../logic/words';

export const RUN_PAGE = 50;

export type PaneRun = RunRow & FeedRow;

export const pane = $state({
  automationId: null as string | null,
  runs: [] as PaneRun[],
  status: 'idle' as 'idle' | 'loading' | 'ready' | 'error',
  error: '',
  loadingMore: false,
  /* there is nothing */
  exhausted: false,
});

let generation = 0;

function newest(a: PaneRun, b: PaneRun): number {
  if (a.number != null && b.number != null && a.number !== b.number) return b.number - a.number;
  return runTime(b) - runTime(a);
}

export async function loadPaneRuns(id: string): Promise<void> {
  generation += 1;
  const mine = generation;
  if (pane.automationId !== id) {
    pane.automationId = id;
    pane.runs = [];
    pane.exhausted = false;
  }
  pane.status = pane.runs.length ? 'ready' : 'loading';
  try {
    const page = await api.listRuns(id, RUN_PAGE, { include_report: true });
    if (mine !== generation) return;
    for (const run of page.runs) keepReport(run, true);
    pane.runs = (page.runs as unknown as PaneRun[]).slice().sort(newest);
    pane.exhausted = page.runs.length < RUN_PAGE;
    pane.status = 'ready';
    pane.error = '';
  } catch (error) {
    if (mine !== generation) return;
    pane.status = 'error';
    pane.error = error instanceof Error ? error.message : String(error);
  }
}

export async function refreshPaneRuns(id: string): Promise<void> {
  if (pane.automationId !== id) return loadPaneRuns(id);
  try {
    const page = await api.listRuns(id, RUN_PAGE);
    if (pane.automationId !== id) return;
    const fresh = page.runs as unknown as PaneRun[];
    const seen = new Set(fresh.map((r) => r.run_id));
    const oldestFresh = fresh.length >= RUN_PAGE ? Math.min(...fresh.map((r) => r.number ?? Infinity)) : -Infinity;
    const kept = pane.runs.filter((r) => !seen.has(r.run_id) && (r.number ?? 0) < oldestFresh);
    pane.runs = [...fresh, ...kept].sort(newest);
    for (const run of fresh) if (run.has_report && !isLive(run.status) && !reports[run.run_id]) ensureReport(run.run_id);
    pane.status = 'ready';
  } catch {
  }
}

export async function loadOlderRuns(): Promise<void> {
  const id = pane.automationId;
  const last = pane.runs[pane.runs.length - 1];
  if (!id || !last || pane.loadingMore) return;
  pane.loadingMore = true;
  try {
    const page = await api.listRuns(id, RUN_PAGE, { before: last.run_id, include_report: true });
    if (pane.automationId !== id) return;
    for (const run of page.runs) keepReport(run, true);
    const have = new Set(pane.runs.map((r) => r.run_id));
    pane.runs = [...pane.runs, ...(page.runs as unknown as PaneRun[]).filter((r) => !have.has(r.run_id))].sort(newest);
    pane.exhausted = page.runs.length < RUN_PAGE;
  } catch {
  } finally {
    pane.loadingMore = false;
  }
}

export async function ensurePaneRun(runId: string): Promise<void> {
  if (pane.runs.some((r) => r.run_id === runId)) return;
  try {
    const run = (await api.getRun(runId)) as unknown as PaneRun & { report?: unknown };
    if (run.automation_id !== pane.automationId || pane.runs.some((r) => r.run_id === runId)) return;
    if (run.has_report && !isLive(run.status)) reports[runId] = { state: 'ready', report: run.report ?? null };
    pane.runs = [...pane.runs, run].sort(newest);
  } catch {
  }
}

export function paneSlot(run: PaneRun): ReportSlot {
  return slotOf(run, lookup);
}
