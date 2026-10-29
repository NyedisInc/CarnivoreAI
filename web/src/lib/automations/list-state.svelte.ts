import { t } from '../i18n/index.svelte';
import * as api from './api';
import { cronWords } from './cron-words';
import { refusalText } from './format';
import { COUNTER_IDS } from './logic/counters';
import { compare, firstResult, previousIndex, type DiffResult, type DiffRun } from './logic/diff';
import { filterRows, previewText, sortRows, type ListRow, type Pill, type PreviewRun, type SortKey } from './logic/list';
import { signalsOf } from './logic/signals';
import type { ReportSlot } from './logic/types';
import { statusWord } from './logic/words';
import { data, openNew, openPane, pageClock, refresh, select } from './page-store.svelte';
import type { EditorStart } from './schedule-prefill';
import { TARGET_FORMS } from './target-forms';
import { templateNameKey, templateTextKey, type Template } from './logic/templates';

export const view = $state({
  q: '',
  pills: [] as Pill[],
  sort: { k: 'light' as SortKey, d: 1 as 1 | -1 },
  dens: 'comfortable' as 'comfortable' | 'compact',
  confirmId: null as string | null,
  busyId: null as string | null,
});

export function kindWords(kind: string): string {
  const key = `automations.target.${kind}`;
  const words = t(key);
  return words === key ? kind : words;
}

function targetText(value: unknown, depth = 0): string[] {
  if (typeof value === 'string') return [value];
  if (typeof value === 'number') return [String(value)];
  if (depth > 3 || value === null || typeof value !== 'object') return [];
  return Object.values(value as Record<string, unknown>).flatMap((v) => targetText(v, depth + 1));
}

export function haystackOf(a: api.Automation): string {
  const project = data.projects.find((p) => p.id === a.project_id)?.name ?? '';
  return [a.name, kindWords(a.target.kind), ...targetText(a.target), a.description ?? '', cronWords(a.trigger.cron), project].join(' ').toLowerCase();
}

export function rowOf(a: api.Automation): ListRow {
  return {
    id: a.automation_id,
    name: a.name,
    enabled: a.enabled,
    kindLabel: kindWords(a.target.kind),
    cronWords: cronWords(a.trigger.cron),
    nextFireAt: a.next_fire_at,
    sig: signalsOf({ recent: a.recent ?? [], median_took_s: a.median_took_s ?? null, newest_output_empty: a.newest_output_empty ?? false }, a.enabled),
  };
}

export function allRows(): ListRow[] {
  return data.automations.map(rowOf);
}

export function narrowed(): boolean {
  return !!view.q.trim() || view.pills.length > 0 || COUNTER_IDS.some((id) => data.pressed[id]);
}

export function visibleRows(): ListRow[] {
  const text = new Map(data.automations.map((a) => [a.automation_id, haystackOf(a)]));
  const counters = data.counts?.counters;
  const pressed = counters ? COUNTER_IDS.filter((id) => data.pressed[id]) : [];
  const counterIds = Object.fromEntries(COUNTER_IDS.map((id) => [id, counters?.[id]?.automation_ids ?? []]));
  const rows = filterRows(allRows(), { q: view.q, pills: view.pills, pressed, counterIds, where: null }, (v) => text.get(v.id) ?? '');
  return sortRows(rows, view.sort.k, view.sort.d);
}

export function resetFilters(): void {
  view.q = '';
  view.pills = [];
  data.pressed = {};
}

async function act(id: string, call: () => Promise<string>): Promise<void> {
  view.busyId = id;
  data.notice = '';
  try {
    data.notice = await call();
  } catch (error) {
    data.notice = refusalText(error);
  } finally {
    view.busyId = null;
  }
  await refresh();
}

export function toggleEnabled(a: api.Automation): Promise<void> {
  const next = !a.enabled;
  return act(a.automation_id, async () => {
    await api.updateAutomation(a.automation_id, a.revision, { enabled: next });
    return t(next ? 'automations.page.toast.switched_on' : 'automations.page.toast.switched_off', { name: a.name });
  });
}

export function runNow(a: api.Automation): Promise<void> {
  return act(a.automation_id, async () => {
    await api.runAutomationNow(a.automation_id);
    return t(a.spends ? 'automations.page.toast.run_started_spends' : 'automations.page.toast.run_started_none', { name: a.name });
  });
}

export async function duplicate(a: api.Automation): Promise<void> {
  const draft: api.AutomationDraft = {
    name: `${a.name} ${t('automations.page.report.copy')}`,
    cron: a.trigger.cron,
    target: JSON.parse(JSON.stringify(a.target)) as api.AutomationTarget,
    delivery: { ...a.delivery },
    enabled: a.enabled,
    description: a.description,
    project_id: a.project_id,
    misfire: a.misfire,
    retry_max: a.retry_max,
    retry_backoff_s: a.retry_backoff_s,
    max_runtime_s: a.max_runtime_s,
  };
  let created: api.Automation | null = null;
  await act(a.automation_id, async () => {
    created = await api.createAutomation(draft);
    return t('automations.page.toast.created', { name: created.name });
  });
  if (created) {
    select((created as api.Automation).automation_id);
    openPane();
  }
}

export function remove(a: api.Automation): Promise<void> {
  view.confirmId = null;
  return act(a.automation_id, async () => {
    await api.deleteAutomation(a.automation_id);
    return t('automations.page.toast.deleted', { name: a.name });
  });
}

const compared = new Map<string, DiffResult | null>();

/* no report to compare */
export async function compareWithPrevious(automationId: string, run: { run_id: string }): Promise<DiffResult | null> {
  const key = `${automationId}:${run.run_id}`;
  if (compared.has(key)) return compared.get(key) ?? null;
  try {
    const { runs } = await api.listRuns(automationId, 12, { include_report: true });
    const slots = new Map<string, ReportSlot>(runs.map((r) => [r.run_id, r.has_report ? { state: 'ready', report: r.report ?? null } : { state: 'ready', report: null }]));
    const at = runs.findIndex((r) => r.run_id === run.run_id);
    if (at < 0) return null;
    const head = { run: runs[at] as unknown as DiffRun, slot: slots.get(run.run_id)! };
    const prev = previousIndex(runs, at, (id) => slots.get(id) ?? { state: 'pending' });
    const result = prev < 0 ? firstResult(head.run) : compare({ run: runs[prev] as unknown as DiffRun, slot: slots.get(runs[prev]!.run_id)! }, head, { statusWord });
    compared.set(key, result);
    return result;
  } catch {
    return null;
  }
}

export function lineFor(run: PreviewRun, cmp: DiffResult | null): string {
  return previewText(run, cmp, pageClock(), data.tz);
}

/* a new automation */
export function startFromTemplate(tpl: Template): void {
  const targets = data.targets;
  if (!targets) return;
  const text = t(templateTextKey(tpl));
  const blank = TARGET_FORMS[tpl.kind === 'agent' ? 'agent' : tpl.kind]?.blank(targets) ?? null;
  const target = blank
    ? tpl.kind === 'agent'
      ? { ...blank, prompt: text }
      : tpl.kind === 'command'
        ? { ...blank, command: text }
        : tpl.kind === 'swarm_card'
          ? { ...blank, title: text }
          : blank
    : null;
  const seed: EditorStart & { cron: string } = { target, projectId: null, name: t(templateNameKey(tpl)), cron: tpl.cron };
  openNew(seed);
}
