import type { Automation, RunSummary } from '../../../lib/automations/api';
import { nextWords, runTimeWords } from '../../lib/run-chart';
import { cap, type ActivityRow, type Capped } from '../../lib/run-queue';
import { inScope, type Scope } from '../../ui/scope-filter';
import { automationArea, byWords, LIVE_STATUSES, type ChartInput, type RunRow } from './model';

export type Translate = (key: string, params?: Record<string, string | number>) => string;

export interface ActivityInput extends ChartInput {
  runs: readonly RunRow[];
}

function liveRuns(automations: readonly Automation[], runs: readonly RunRow[]): [RunSummary, string][] {
  const found = new Map<string, [RunSummary, string]>();
  for (const run of runs) if (LIVE_STATUSES.has(run.status)) found.set(run.run_id, [run, run.automation_name]);
  for (const automation of automations) {
    const last = automation.last_run;
    if (last && LIVE_STATUSES.has(last.status) && !found.has(last.run_id)) found.set(last.run_id, [last, automation.name]);
  }
  const began = (run: RunSummary): number => run.started_at ?? run.slot_at ?? 0;
  return [...found.values()].sort((a, b) => began(b[0]) - began(a[0]));
}

export function scheduledRunning(input: ActivityInput, nowS: number, scope: Scope, t: Translate): ActivityRow[] {
  if (!inScope('global', scope)) return [];
  return liveRuns(input.automations, input.runs).map(([run, name]) => {
    const began = run.started_at ?? run.slot_at;
    const by = byWords(run);
    return {
      id: `run:${run.run_id}`,
      name,
      area: t(by.key, by.params),
      time: began === null ? t('opscenter.chart.running') : runTimeWords(Math.max(0, nowS - began) * 1000),
    };
  });
}

export function scheduledQueue(input: ActivityInput, nowS: number, scope: Scope, t: Translate): Capped<ActivityRow> {
  const due: { at: number; row: ActivityRow }[] = [];
  if (inScope('global', scope)) {
    for (const automation of input.automations) {
      if (!automation.enabled || automation.next_fire_at === null) continue;
      const area = automationArea(automation, input.projects);
      due.push({ at: automation.next_fire_at, row: { id: `auto:${automation.automation_id}`, name: automation.name, area: area ?? t('pipeline.chart.machine'), time: '' } });
    }
  }
  if (inScope('sessions', scope)) {
    for (const item of input.huddle) {
      if (item.paused || item.fireAt === null) continue;
      const area = item.project ?? (item.list === 'all' ? t('opscenter.chart.shared') : t('pipeline.chart.machine'));
      due.push({ at: item.fireAt, row: { id: `huddle:${item.list}:${item.item}`, name: item.title, area, time: '' } });
    }
  }
  due.sort((a, b) => a.at - b.at);
  return cap(due.map(({ at, row }) => ({ ...row, time: nextWords(Math.max(0, at - nowS)) })));
}
