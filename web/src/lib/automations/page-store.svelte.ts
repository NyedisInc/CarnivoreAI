import { resourcePush } from '../resource-push/boot';
import { whenListingPushBooted, type ListingPushGlobal } from '../listing-push/boot';
import { readTab, writeTab } from '../../opscenter/ui/tab-memory';
import * as api from './api';
import { feed, loadFeed, refreshFeed, releaseFeedCaches } from './feed-store.svelte';
import { refusalText } from './format';
import { COUNTER_IDS } from './logic/counters';
import { headerSentence } from './logic/list';
import { signalsOf } from './logic/signals';
import type { CounterId } from './logic/types';
import { clockFor, DAY, runTime, type Clock } from './logic/words';
import { startReadState } from './read-state.svelte';
import { clearRunAddress, onRoute, takeRoute, writeFeedRun } from './route';
import { editorStart, type EditorStart, type SchedulePrefill } from './schedule-prefill';
import {
  ADVANCED_TAB_KEY,
  ADVANCED_TABS,
  AUTOMATIONS_TAB_KEY,
  AUTOMATIONS_TABS,
  DEFAULT_ADVANCED_TAB,
  DEFAULT_TAB,
  effectiveAdvancedTab,
  effectiveTab,
  type AdvancedTab,
  type AutomationsTab,
} from './tabs';
import { offeredKinds, TARGET_FORMS } from './target-forms';
import { sessionChoices } from './sessions-view';
import { t } from '../i18n/index.svelte';

export const AUTOMATION_TOPICS = ['automations', 'automation_runs', 'automation_commands'] as const;
const POLL_MS = 15000;
const COUNTS_MIN_GAP_MS = 60000;
const PHONE_PX = 700;

export interface FeedFilters {
  status: string;
  automation: string;
  trigger: string;
  host: string;
}
export const NO_HOST = '__none__';

export interface DrawerTarget {
  kind: 'automation' | 'run';
  id: string;
}

export const data = $state({
  status: 'loading' as 'loading' | 'ready' | 'error',
  error: '',
  automations: [] as api.Automation[],
  tz: 'UTC',
  paused: false,
  targets: null as api.Targets | null,
  projects: [] as api.ProjectChoice[],
  sessions: [] as api.SessionChoice[],
  sessionsWanted: false,
  counts: null as api.RunCounts | null,
  now: Math.floor(Date.now() / 1000),
  top: effectiveTab(readTab(AUTOMATIONS_TAB_KEY, AUTOMATIONS_TABS, DEFAULT_TAB)) as AutomationsTab,
  tab: effectiveAdvancedTab(readTab(ADVANCED_TAB_KEY, ADVANCED_TABS, DEFAULT_ADVANCED_TAB)) as AdvancedTab,
  drawer: null as DrawerTarget | null,
  pressed: {} as Partial<Record<CounterId, boolean>>,
  where: '',
  filters: { status: '', automation: '', trigger: '', host: '' } as FeedFilters,
  feedRunId: null as string | null,
  selectedId: null as string | null,
  paneOpen: false,
  paneTab: 'output' as 'output' | 'runs' | 'overview' | 'log',
  paneRunId: null as string | null,
  paneMode: null as 'edit' | 'new' | null,
  seed: null as EditorStart | null,
  seedCount: 0,
  logOpen: false,
  commandsOpen: false,
  notice: '',
  pendingEdit: null as string | null,
  pendingNew: null as SchedulePrefill | null,
  fixture: false,
});

let booted = false;
let countsTimer: ReturnType<typeof setTimeout> | null = null;
let lastCountsTimerAt = 0;

function isPhone(): boolean {
  return typeof window !== 'undefined' && window.innerWidth <= PHONE_PX;
}

export function firstAttention(): string | null {
  const ranked = data.automations
    .filter((a) => a.recent)
    .map((a) => ({ id: a.automation_id, name: a.name.toLowerCase(), rank: signalsOf({ recent: a.recent!, median_took_s: a.median_took_s ?? null, newest_output_empty: a.newest_output_empty ?? false }, a.enabled).attentionRank }));
  const pool = ranked.length ? ranked : data.automations.map((a) => ({ id: a.automation_id, name: a.name.toLowerCase(), rank: 0 }));
  pool.sort((a, b) => a.rank - b.rank || (a.name < b.name ? -1 : a.name > b.name ? 1 : 0));
  return pool[0]?.id ?? null;
}

export function pageClock(): Clock {
  return clockFor(data.tz);
}

export function sentence(): string {
  const rows = data.automations;
  const next = rows
    .filter((a) => a.enabled && a.next_fire_at != null)
    .sort((a, b) => a.next_fire_at! - b.next_fire_at!)[0];
  const attention = rows.filter((a) => a.recent && signalsOf({ recent: a.recent, median_took_s: a.median_took_s ?? null, newest_output_empty: a.newest_output_empty ?? false }, a.enabled).attention).length;
  const runs24h = data.counts
    ? data.counts.counters.succeeded_24h.count + data.counts.counters.failed_24h.count
    : rows.reduce((sum, a) => sum + (a.recent ?? []).filter((r) => runTime(r) >= data.now - DAY).length, 0);
  return headerSentence(
    {
      total: rows.length,
      on: rows.filter((a) => a.enabled).length,
      attention,
      paused: data.paused,
      next: next ? { name: next.name, at: next.next_fire_at! } : null,
      runs24h,
      failed24h: data.counts?.counters.failed_24h.count ?? 0,
    },
    pageClock(),
    data.now,
  );
}

export function whereIds(where: string): string[] | null {
  if (!where) return null;
  const files = (a: api.Automation) => a.files_under ?? { session_uuid: null, project_id: null };
  const match = (a: api.Automation): boolean => {
    const f = files(a);
    if (where === 'u') return f.session_uuid === null && f.project_id === null;
    if (where.startsWith('p:')) return String(f.project_id) === where.slice(2);
    return f.session_uuid === where.slice(2);
  };
  return data.automations.filter(match).map((a) => a.automation_id);
}

export function feedParams(): api.FeedParams | null {
  const where = whereIds(data.where);
  let ids: string[] | null = where;
  if (data.filters.automation) {
    if (where && !where.includes(data.filters.automation)) return null;
    ids = [data.filters.automation];
  }
  if (ids && ids.length === 0) return null;
  const params: api.FeedParams = {};
  if (ids) params.automation_id = ids;
  if (data.filters.status) params.status = [data.filters.status];
  if (data.filters.trigger) params.trigger = [data.filters.trigger];
  if (data.filters.host === NO_HOST) params.no_host = true;
  else if (data.filters.host) params.host = [data.filters.host];
  const counters = COUNTER_IDS.filter((id) => data.pressed[id]);
  if (counters.length) params.counter = counters;
  return params;
}

export async function reloadFeed(): Promise<void> {
  const params = feedParams();
  if (!params) {
    feed.runs = [];
    feed.total = 0;
    feed.nextBefore = null;
    feed.status = 'ready';
    return;
  }
  await loadFeed(params);
}

export async function refreshCounts(): Promise<void> {
  try {
    data.counts = await api.getRunCounts();
    data.now = Math.floor(Date.now() / 1000);
    armCountsTimer(data.counts.next_change_at);
  } catch {
    data.counts = null;
  }
}

function armCountsTimer(at: number | null): void {
  if (countsTimer) clearTimeout(countsTimer);
  countsTimer = null;
  if (at == null) return;
  const gap = Math.max(COUNTS_MIN_GAP_MS, at * 1000 - Date.now() + 500, lastCountsTimerAt + COUNTS_MIN_GAP_MS - Date.now());
  countsTimer = setTimeout(() => {
    lastCountsTimerAt = Date.now();
    void refreshCounts();
  }, gap);
}

export async function refresh(): Promise<void> {
  try {
    const [list, targets] = await Promise.all([api.listAutomations(), api.listTargets(), refreshCounts()]);
    data.automations = list.automations;
    data.paused = list.scheduler?.paused === true;
    if (list.tz) data.tz = list.tz;
    data.targets = targets;
    if (data.projects.length === 0) await loadProjects();
    if (data.sessionsWanted) await loadSessions();
    if (data.selectedId && !list.automations.some((a) => a.automation_id === data.selectedId)) closeSelection();
    data.status = 'ready';
    data.error = '';
    if (!booted) {
      booted = true;
      if (!data.selectedId && !data.pendingEdit && !data.paneRunId) {
        data.selectedId = firstAttention();
        data.paneOpen = data.selectedId !== null && data.top === 'advanced' && data.tab === 'automations' && !isPhone();
      }
    }
    resolvePending();
  } catch (error) {
    data.status = 'error';
    data.error = refusalText(error);
  }
}

async function loadProjects(): Promise<void> {
  try {
    data.projects = (await api.listProjectChoices()).filter((p) => p.id !== null);
  } catch {
    data.projects = [];
  }
}

async function loadSessions(): Promise<void> {
  try {
    const rows = await api.listSessionRecords();
    if (Array.isArray(rows)) data.sessions = rows;
  } catch {
  }
}

export async function wantSessions(): Promise<void> {
  data.sessionsWanted = true;
  await loadSessions();
}

export function sessionOptions(): api.SessionChoice[] {
  return sessionChoices(data.sessions, data.automations);
}

function closeSelection(): void {
  data.selectedId = null;
  closePane();
}

export function select(id: string | null): void {
  data.selectedId = id;
  data.paneRunId = null;
  if (id === null) closePane();
}

export function closePane(): void {
  data.paneOpen = false;
  data.paneMode = null;
  data.paneRunId = null;
  data.seed = null;
  clearRunAddress();
}

export function openPane(): void {
  if (data.selectedId) data.paneOpen = true;
}

export function openNew(seed: EditorStart | null = null): void {
  data.seed = seed;
  data.seedCount += 1;
  data.notice = '';
  data.paneMode = 'new';
  data.paneOpen = true;
}

export function openEdit(id: string): void {
  data.selectedId = id;
  data.seed = null;
  data.notice = '';
  data.paneMode = 'edit';
  data.paneOpen = true;
}

export function feedShown(): boolean {
  return data.top === 'sessions' || (data.top === 'advanced' && data.tab === 'sessions');
}

function ensureFeed(): void {
  void wantSessions();
  if (feed.status === 'idle') void reloadFeed();
}

export function setTab(id: string, remember = false): void {
  const next = effectiveAdvancedTab(id);
  if (remember) writeTab(ADVANCED_TAB_KEY, next);
  if (next === data.tab) return;
  data.tab = next;
  if (next === 'sessions') {
    closePane();
    ensureFeed();
  } else {
    writeFeedRun(null);
  }
}

export function setTop(id: string, remember = false): void {
  const next = effectiveTab(id);
  if (remember) writeTab(AUTOMATIONS_TAB_KEY, next);
  if (next === data.top) return;
  data.top = next;
  if (next === 'sessions') closePane();
  if (feedShown()) ensureFeed();
  else writeFeedRun(null);
}

export function openDrawer(kind: DrawerTarget['kind'], id: string): void {
  data.drawer = { kind, id };
  if (kind === 'run' && data.top === 'sessions') writeFeedRun(id);
}

export function closeDrawer(): void {
  const was = data.drawer;
  data.drawer = null;
  if (was?.kind === 'run' && data.top === 'sessions') writeFeedRun(null);
}

export function openInAdvanced(kind: DrawerTarget['kind'], id: string): void {
  data.drawer = null;
  data.top = 'advanced';
  if (kind === 'run') {
    data.tab = 'sessions';
    closePane();
    data.feedRunId = id;
    ensureFeed();
    return;
  }
  data.tab = 'automations';
  writeFeedRun(null);
  select(id);
  data.paneMode = null;
  openPane();
}

export function togglePressed(id: CounterId): void {
  data.pressed = { ...data.pressed, [id]: !data.pressed[id] };
  if (feedShown()) void reloadFeed();
}

export function setFilters(patch: Partial<FeedFilters> & { where?: string }): void {
  if (patch.where !== undefined) data.where = patch.where;
  const { where: _where, ...rest } = patch;
  data.filters = { ...data.filters, ...rest };
  void reloadFeed();
}

export async function setPaused(next: boolean): Promise<void> {
  data.notice = '';
  try {
    await api.setSchedulerPaused(next);
  } catch (error) {
    data.notice = refusalText(error);
  }
  await refresh();
}

async function openRunLink(runId: string): Promise<void> {
  data.top = 'advanced';
  data.tab = 'automations';
  try {
    const run = await api.getRun(runId);
    data.selectedId = run.automation_id;
    data.paneRunId = run.run_id;
    data.paneTab = 'output';
    data.paneMode = null;
    data.paneOpen = true;
  } catch (error) {
    data.notice = refusalText(error);
  }
}

function resolvePending(): void {
  if (data.status !== 'ready') return;
  if (data.pendingEdit) {
    const found = data.automations.find((a) => a.automation_id === data.pendingEdit);
    const id = data.pendingEdit;
    data.pendingEdit = null;
    if (found) openEdit(id);
    else data.notice = t('automations.edit_link.gone');
  }
  if (data.pendingNew && data.targets) {
    const prefill = data.pendingNew;
    data.pendingNew = null;
    void startNew(prefill, data.targets);
  }
}

async function startNew(prefill: SchedulePrefill, targets: api.Targets): Promise<void> {
  if (prefill.kind === 'session') await wantSessions();
  const kinds = offeredKinds(targets);
  if (prefill.kind === 'session' && !kinds.includes('session_message')) {
    data.notice = t('automations.prefill.no_session_runner');
    return;
  }
  const first = kinds[0] ?? '';
  data.top = 'advanced';
  data.tab = 'automations';
  openNew(editorStart(prefill, TARGET_FORMS[first]?.blank(targets) ?? null, data.sessions, data.projects));
}

onRoute('sessions', () => setTop('sessions'));
onRoute('advanced', () => setTop('advanced'));
onRoute('session', (route) => {
  setTop('advanced');
  setTab('sessions');
  setFilters({ where: `s:${route.uuid}` });
});
onRoute('feed_run', (route) => {
  setTop('sessions');
  openDrawer('run', route.runId);
});
onRoute('run', (route) => void openRunLink(route.runId));
onRoute('edit', (route) => {
  data.pendingEdit = route.id;
  data.top = 'advanced';
  data.tab = 'automations';
  resolvePending();
});
onRoute('new', (route) => {
  data.pendingNew = route.prefill;
  resolvePending();
});

export function takeAddress(): void {
  takeRoute();
}

export function follow(): () => void {
  void refresh();
  if (feedShown()) void wantSessions();
  const stopTopics = resourcePush().pushOrPoll(() => void refresh(), POLL_MS, AUTOMATION_TOPICS);
  const stopFeed = resourcePush().pushOrPoll(
    () => {
      const params = feedParams();
      if (params) void refreshFeed(params);
    },
    POLL_MS,
    ['automation_runs'],
  );
  const stopRead = startReadState();
  let stopSessions: (() => void) | null = null;
  let stopped = false;
  whenListingPushBooted(() => {
    const push = (globalThis as { ListingPush?: ListingPushGlobal }).ListingPush;
    if (stopped || !push) return;
    stopSessions = push.pushOrPoll(() => void (data.sessionsWanted ? loadSessions() : undefined), POLL_MS, ['records']);
  });
  const minute = setInterval(() => (data.now = Math.floor(Date.now() / 1000)), 60000);
  const visible = (): void => {
    if (document.visibilityState === 'visible') void refreshCounts();
  };
  document.addEventListener('visibilitychange', visible);
  return () => {
    stopped = true;
    stopTopics();
    stopFeed();
    stopRead();
    stopSessions?.();
    clearInterval(minute);
    document.removeEventListener('visibilitychange', visible);
    if (countsTimer) clearTimeout(countsTimer);
    countsTimer = null;
    releaseFeedCaches();
  };
}
