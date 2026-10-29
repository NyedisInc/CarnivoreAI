/*  hidden  */
import * as api from '../api';
import { refusalText } from '../format';
import { reports } from '../feed-store.svelte';
import { resetFilters as resetListFilters, visibleRows } from '../list-state.svelte';
import { isLive } from '../logic/words';
import type { FeedRun } from '../logic/types';
import { data, openPane, select, setFilters, setTab } from '../page-store.svelte';

export const FIRST_LIMIT = 120;
export const MORE_LIMIT = 50;
const PHONE_PX = 700;

export const fv = $state({
  q: '',
  changedOnly: false,
  unreadOnly: false,
  filtersOpen: false,
  limit: FIRST_LIMIT,
  expanded: {} as Record<string, boolean>,
  sheet: false,
});

export const outside = $state({ run: null as FeedRun | null });

export function isPhone(): boolean {
  return typeof window !== 'undefined' && window.innerWidth <= PHONE_PX;
}

export function anyFilter(): boolean {
  const f = data.filters;
  return !!(fv.q.trim() || fv.changedOnly || fv.unreadOnly || data.where || f.status || f.automation || f.trigger || f.host || Object.values(data.pressed).some(Boolean));
}

export function anySelect(): boolean {
  const f = data.filters;
  return !!(data.where || f.status || f.automation || f.trigger || f.host);
}

export function clearAllFilters(): void {
  fv.q = '';
  fv.changedOnly = false;
  fv.unreadOnly = false;
  fv.limit = FIRST_LIMIT;
  data.pressed = {};
  setFilters({ where: '', status: '', automation: '', trigger: '', host: '' });
}

export function openAutomation(automationId: string, runId: string | null): void {
  if (!data.automations.some((a) => a.automation_id === automationId)) return;
  setTab('automations');
  if (!visibleRows().some((r) => r.id === automationId)) resetListFilters();
  select(automationId);
  data.paneRunId = runId;
  data.paneTab = 'output';
  data.paneMode = null;
  openPane();
}

export async function loadOutside(runId: string): Promise<void> {
  if (outside.run?.run_id === runId) return;
  try {
    const run = (await api.getRun(runId)) as unknown as FeedRun & { report?: unknown };
    const name = data.automations.find((a) => a.automation_id === run.automation_id)?.name ?? '';
    if (run.has_report && !isLive(run.status) && !reports[run.run_id]) reports[run.run_id] = { state: 'ready', report: run.report ?? null };
    outside.run = { ...run, automation_name: run.automation_name ?? name };
  } catch (error) {
    data.notice = refusalText(error);
    outside.run = null;
  }
}
