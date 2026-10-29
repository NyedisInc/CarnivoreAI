import type { Automation, RunSummary } from '../../../lib/automations/api';
import type { TaskManagerSchedule } from '../../../lib/task-manager-schedules/task-manager-scheduled';
import type { ChartColumns } from '../../lib/run-chart';
import { inScope, type RowScope, type Scope } from '../../ui/scope-filter';

export type Result = 'ok' | 'error' | 'skipped';

export type Mark = Result | 'running' | 'none';

export const MARK_KEYS: Readonly<Record<Mark, string>> = {
  ok: 'opscenter.chart.outcome.ok',
  error: 'opscenter.chart.outcome.error',
  skipped: 'opscenter.chart.outcome.skipped',
  running: 'opscenter.chart.outcome.running',
  none: 'opscenter.chart.outcome.none',
};

export interface RunRow extends RunSummary {
  automation_name: string;
}

export interface Words {
  key: string;
  params: Record<string, string | number>;
}

export interface ScheduledRow extends Record<string, unknown> {
  id: string;
  scope: RowScope;
  name: string;
  by: Words | null;
  area: string | null;
  shared: boolean;
  runSeconds: number | null;
  agoSeconds: number | null;
  nextSeconds: number | null;
  paused: boolean;
  mark: Mark;
}

export interface ChartInput {
  automations: readonly Automation[];
  projects: Readonly<Record<number, string>>;
  huddle: readonly TaskManagerSchedule[];
}

export const LIVE_STATUSES: ReadonlySet<string> = new Set(['claimed', 'running', 'waiting_on_you']);

const TRIGGER_KEYS: Readonly<Record<string, string>> = {
  schedule: 'opscenter.chart.by.schedule',
  catch_up: 'opscenter.chart.by.catch_up',
  retry: 'opscenter.chart.by.retry',
};

export function resultOf(status: string): Result {
  if (status === 'succeeded') return 'ok';
  if (status === 'failed') return 'error';
  return 'skipped';
}

export function byWords(run: Pick<RunSummary, 'trigger' | 'notes'>): Words {
  const fixed = TRIGGER_KEYS[run.trigger];
  if (fixed) return { key: fixed, params: {} };
  if (run.trigger !== 'run_now') return { key: 'opscenter.chart.by.other', params: {} };
  const by = run.notes?.by;
  if ((by?.kind === 'app' || by?.kind === 'mcp') && by.name) return { key: 'opscenter.chart.by.run_now_named', params: { name: by.name } };
  if (by?.kind === 'app') return { key: 'opscenter.chart.by.run_now_owner', params: {} };
  if (by?.kind === 'mcp') return { key: 'opscenter.chart.by.run_now_agent', params: {} };
  return { key: 'opscenter.chart.by.run_now', params: {} };
}

export function automationArea(automation: Pick<Automation, 'target' | 'project_id'>, projects: Readonly<Record<number, string>>): string | null {
  const session = automation.target.session_name;
  if (typeof session === 'string' && session.trim()) return session;
  const project = automation.project_id ?? (typeof automation.target.project_id === 'number' ? automation.target.project_id : null);
  return project !== null ? (projects[project] ?? null) : null;
}

function lastMoment(run: RunSummary | null | undefined): number {
  if (!run) return -1;
  return run.ended_at ?? run.started_at ?? run.slot_at ?? -1;
}

export function automationRows(automations: readonly Automation[], projects: Readonly<Record<number, string>>, nowS: number): ScheduledRow[] {
  const rows: { row: ScheduledRow; live: boolean; moment: number; next: number }[] = [];
  for (const automation of automations) {
    const last = automation.last_run ?? null;
    const due = automation.enabled && automation.next_fire_at !== null ? automation.next_fire_at : null;
    if (!last && due === null) continue;
    const live = last !== null && LIVE_STATUSES.has(last.status);
    const started = last?.started_at ?? null;
    const ended = last?.ended_at ?? null;
    const runSeconds = live ? (started === null ? null : Math.max(0, nowS - started)) : started !== null && ended !== null ? Math.max(0, ended - started) : null;
    const endedAt = ended ?? started;
    rows.push({
      live,
      moment: lastMoment(last),
      next: due ?? Number.POSITIVE_INFINITY,
      row: {
        id: `auto:${automation.automation_id}`,
        scope: 'global',
        name: automation.name,
        by: last ? byWords(last) : null,
        area: automationArea(automation, projects),
        shared: false,
        runSeconds,
        agoSeconds: !live && last && endedAt !== null ? Math.max(0, nowS - endedAt) : null,
        nextSeconds: due === null ? null : Math.max(0, due - nowS),
        paused: false,
        mark: live ? 'running' : last ? resultOf(last.status) : 'none',
      },
    });
  }
  rows.sort((a, b) => Number(b.live) - Number(a.live) || b.moment - a.moment || a.next - b.next);
  return rows.map((entry) => entry.row);
}

export function taskManagerRows(huddle: readonly TaskManagerSchedule[], nowS: number): ScheduledRow[] {
  return huddle
    .map((item): ScheduledRow => ({
      id: `huddle:${item.list}:${item.item}`,
      scope: 'sessions',
      name: item.title,
      by: { key: 'opscenter.chart.by.schedule', params: {} },
      area: item.project ?? null,
      shared: item.list === 'all',
      runSeconds: null,
      agoSeconds: null,
      nextSeconds: item.paused || item.fireAt === null ? null : Math.max(0, item.fireAt - nowS),
      paused: item.paused,
      mark: item.state === 'failed' ? 'error' : 'none',
    }))
    .sort((a, b) => (a.nextSeconds ?? Number.POSITIVE_INFINITY) - (b.nextSeconds ?? Number.POSITIVE_INFINITY));
}

export function scheduledChart(input: ChartInput, nowMs: number, scope: Scope): ScheduledRow[] {
  const nowS = nowMs / 1000;
  return [
    ...(inScope('global', scope) ? automationRows(input.automations, input.projects, nowS) : []),
    ...(inScope('sessions', scope) ? taskManagerRows(input.huddle, nowS) : []),
  ];
}

export const SCHEDULED_COLUMNS: ChartColumns = {
  all: [
    { key: 'name', headKey: 'opscenter.column.name', minPx: 48, weight: 1.6, insetPx: 12 },
    { key: 'by', headKey: 'opscenter.column.ran_by', minPx: 48, weight: 1.2 },
    { key: 'area', headKey: 'opscenter.column.area', minPx: 48, weight: 1.2 },
    { key: 'runTime', headKey: 'opscenter.column.run_time', minPx: 40, weight: 0.01, align: 'end', fit: 'runTime' },
    { key: 'ago', headKey: 'opscenter.column.ago', minPx: 40, weight: 0.01, align: 'end', fit: 'ago' },
    { key: 'next', headKey: 'opscenter.column.next_run', minPx: 40, weight: 0.01, align: 'end', insetPx: 12, fit: 'next' },
  ],
  narrow: ['name', 'by', 'runTime', 'ago', 'next'],
  wideAt: 440,
  tight: ['name', 'runTime', 'ago', 'next'],
  tightAt: 340,
  phone: [
    { key: 'name', headKey: '', minPx: 0, weight: 1, line: 1 },
    { key: 'ago', headKey: '', minPx: 0, weight: 0, align: 'end', line: 1 },
    { key: 'by', headKey: '', minPx: 0, weight: 1, line: 2 },
    { key: 'next', headKey: '', minPx: 0, weight: 0, align: 'end', line: 2 },
  ],
};
