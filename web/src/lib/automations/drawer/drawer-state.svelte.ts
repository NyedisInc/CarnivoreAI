import * as api from '../api';
import { refusalText } from '../format';
import { reports } from '../feed-store.svelte';
import { isLive } from '../logic/words';
import { nextFires } from './drawer-model';

const RUNS = 20;

export const dr = $state({
  key: '',
  status: 'idle' as 'idle' | 'loading' | 'ready' | 'error',
  error: '',
  runs: [] as api.RunSummary[],
  run: null as api.RunDetail | null,
  fires: [] as number[],
});

let generation = 0;

function keepReports(runs: readonly (api.RunSummary & { report?: unknown; report_omitted?: boolean })[]): void {
  for (const run of runs) {
    if (!run.has_report || isLive(run.status) || reports[run.run_id] || run.report_omitted || !('report' in run)) continue;
    reports[run.run_id] = { state: 'ready', report: run.report ?? null };
  }
}

function begin(key: string): number {
  generation += 1;
  dr.key = key;
  dr.status = 'loading';
  dr.error = '';
  dr.runs = [];
  dr.run = null;
  dr.fires = [];
  return generation;
}

export function resetDrawer(): void {
  generation += 1;
  dr.key = '';
  dr.status = 'idle';
  dr.runs = [];
  dr.run = null;
  dr.fires = [];
}

export async function loadAutomation(id: string, cron: string, rowNext: number | null, enabled: boolean): Promise<void> {
  const mine = begin(`automation:${id}`);
  try {
    const [page, preview] = await Promise.all([
      api.listRuns(id, RUNS),
      enabled ? api.previewSchedule(cron).catch(() => null) : Promise.resolve(null),
    ]);
    if (mine !== generation) return;
    dr.runs = page.runs;
    dr.fires = enabled ? nextFires(preview, rowNext) : [];
    dr.status = 'ready';
  } catch (error) {
    if (mine !== generation) return;
    dr.error = refusalText(error);
    dr.status = 'error';
  }
}

export async function loadRun(runId: string): Promise<void> {
  const mine = begin(`run:${runId}`);
  try {
    const run = await api.getRun(runId);
    if (mine !== generation) return;
    if (run.has_report && !isLive(run.status) && !reports[run.run_id]) reports[run.run_id] = { state: 'ready', report: run.report ?? null };
    dr.run = run;
    const page = await api.listRuns(run.automation_id, RUNS, { include_report: true }).catch(() => null);
    if (mine !== generation) return;
    if (page) {
      keepReports(page.runs);
      dr.runs = page.runs;
    }
    dr.status = 'ready';
  } catch (error) {
    if (mine !== generation) return;
    dr.error = refusalText(error);
    dr.status = 'error';
  }
}
