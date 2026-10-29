/* the plugins page */
import { ApiError, authFetch, resourcePush } from '../sdk';
import type { TaskManagerViewMode } from './task-manager-status-sections';
import { DEFAULT_DENSITY, densityFrom, type HuddleDensity } from './huddle-density';

const CPLUGS_TOPIC = 'cplugs';
const POLL_MS = 60_000;
export const HIDE_COMPLETED = 'hideCompleted';
export const VIEW = 'view';
export const DENSITY = 'density';
export const ACCORDION = 'accordion';
const LEGACY_CLAUDE_VIEW = 'claude';
export const SHOW_TAB = 'showTab';
export const SHOW_EMPTY_GROUPS = 'showEmptyGroups';

export const BADGE_STATUSES = ['question', 'review', 'open', 'working', 'waiting', 'scheduled'] as const;
export type BadgeStatus = (typeof BADGE_STATUSES)[number];
export const BADGE_SETTING: Readonly<Record<BadgeStatus, string>> = {
  question: 'badgeQuestions', review: 'badgeReviews', open: 'badgeOpen', working: 'badgeWorking', waiting: 'badgeWaiting', scheduled: 'badgeScheduled',
};
export const BADGE_DEFAULT: Readonly<Record<BadgeStatus, boolean>> = { question: true, review: true, open: false, working: false, waiting: false, scheduled: false };

export function badgeFrom(settings: Record<string, unknown> | undefined): Record<BadgeStatus, boolean> {
  const out = { ...BADGE_DEFAULT };
  for (const status of BADGE_STATUSES) {
    const stored = settings?.[BADGE_SETTING[status]];
    if (typeof stored === 'boolean') out[status] = stored;
  }
  return out;
}

interface CplugRow {
  revision?: number;
  settings?: Record<string, unknown>;
}

export const taskManagerPrefs = $state<{ hideCompleted: boolean; view: TaskManagerViewMode; density: HuddleDensity; accordion: boolean; showTab: boolean; showEmptyGroups: boolean; badge: Record<BadgeStatus, boolean>; revision: number | null; loaded: boolean }>({
  hideCompleted: false, showTab: true, showEmptyGroups: false, badge: { ...BADGE_DEFAULT }, view: 'status', density: DEFAULT_DENSITY, accordion: false, revision: null, loaded: false,
});

const viewListeners = new Set<(view: TaskManagerViewMode) => void>();
const hideListeners = new Set<(hide: boolean) => void>();

export function onHideCompletedChange(run: (hide: boolean) => void): () => void {
  hideListeners.add(run);
  return () => hideListeners.delete(run);
}

export function onViewChange(run: (view: TaskManagerViewMode) => void): () => void {
  viewListeners.add(run);
  return () => viewListeners.delete(run);
}

export function viewFrom(settings: Record<string, unknown> | undefined): TaskManagerViewMode {
  const view = settings?.[VIEW];
  if (view === LEGACY_CLAUDE_VIEW) return 'area';
  return view === 'area' ? 'area' : 'status';
}

function adopt(row: CplugRow | null | undefined): void {
  if (!row) return;
  const firstAdoption = !taskManagerPrefs.loaded;
  taskManagerPrefs.loaded = true;
  if (typeof row.revision === 'number') taskManagerPrefs.revision = row.revision;
  const hide = row.settings?.[HIDE_COMPLETED] === true;
  const hideFlipped = hide !== taskManagerPrefs.hideCompleted;
  taskManagerPrefs.hideCompleted = hide;
  taskManagerPrefs.density = densityFrom(row.settings);
  taskManagerPrefs.accordion = row.settings?.[ACCORDION] === true;
  taskManagerPrefs.showTab = row.settings?.[SHOW_TAB] !== false;
  taskManagerPrefs.showEmptyGroups = row.settings?.[SHOW_EMPTY_GROUPS] === true;
  taskManagerPrefs.badge = badgeFrom(row.settings);
  const view = viewFrom(row.settings);
  if (row.settings?.[VIEW] === LEGACY_CLAUDE_VIEW) void writeSetting(VIEW, 'area');
  if (view !== taskManagerPrefs.view) {
    taskManagerPrefs.view = view;
    if (!firstAdoption) for (const run of viewListeners) run(view);
  }
  if (hideFlipped) for (const run of hideListeners) run(hide);
}

let prefsEpoch = 0;
let writesInFlight = 0;
let newestWrite = 0;

function adoptRevisionOnly(row: CplugRow | null | undefined): void {
  if (typeof row?.revision === 'number' && row.revision > (taskManagerPrefs.revision ?? 0)) taskManagerPrefs.revision = row.revision;
}

let markSettled: () => void = () => {};
const settled = new Promise<void>((resolve) => {
  markSettled = resolve;
});

export function prefsSettled(): Promise<void> {
  return settled;
}

export async function refreshPrefs(): Promise<void> {
  const epoch = prefsEpoch;
  try {
    const row = await authFetch<CplugRow>('/cplugs/huddle');
    if (epoch !== prefsEpoch || writesInFlight > 0) adoptRevisionOnly(row);
    else adopt(row);
  } catch {
  } finally {
    markSettled();
  }
}

let following = false;

export function followPrefs(): void {
  if (following) return;
  following = true;
  const push = resourcePush();
  push.onChange((topics) => {
    if (topics.includes(CPLUGS_TOPIC)) void refreshPrefs();
  });
  push.pushOrPoll(() => void refreshPrefs(), POLL_MS, [CPLUGS_TOPIC]);
  void refreshPrefs();
}

function staleCurrent(error: unknown): CplugRow | null {
  if (!(error instanceof ApiError) || error.status !== 409) return null;
  const detail = (error.payload as { detail?: { current?: CplugRow } } | null)?.detail;
  return detail?.current ?? null;
}

async function writeSetting(key: string, value: unknown): Promise<boolean> {
  if (taskManagerPrefs.revision === null) await refreshPrefs();
  const mine = ++newestWrite;
  writesInFlight += 1;
  prefsEpoch += 1;
  try {
    for (let attempt = 0; attempt < 2; attempt += 1) {
      try {
        const row = await authFetch<CplugRow>('/cplugs/huddle', {
          method: 'PUT', body: JSON.stringify({ revision: taskManagerPrefs.revision ?? 0, settings: { [key]: value } }),
        });
        if (mine === newestWrite) adopt(row);
        else adoptRevisionOnly(row);
        return true;
      } catch (error) {
        const current = staleCurrent(error);
        if (current && attempt === 0) {
          adoptRevisionOnly(current);
          continue;
        }
        console.warn(`huddle: could not store ${key}`, error);
        break;
      }
    }
    return false;
  } finally {
    writesInFlight -= 1;
    prefsEpoch += 1;
  }
}

export async function setHideCompleted(on: boolean): Promise<boolean> {
  const before = taskManagerPrefs.hideCompleted;
  taskManagerPrefs.hideCompleted = on;
  if (await writeSetting(HIDE_COMPLETED, on)) {
    if (on !== before) for (const run of hideListeners) run(on);
    return true;
  }
  taskManagerPrefs.hideCompleted = before;
  return false;
}

export async function setView(view: TaskManagerViewMode): Promise<boolean> {
  if (view === taskManagerPrefs.view) return true;
  const before = taskManagerPrefs.view;
  taskManagerPrefs.view = view;
  if (await writeSetting(VIEW, view)) {
    for (const run of viewListeners) run(view);
    return true;
  }
  taskManagerPrefs.view = before;
  return false;
}

export async function setDensity(density: HuddleDensity): Promise<boolean> {
  if (density === taskManagerPrefs.density) return true;
  const before = taskManagerPrefs.density;
  taskManagerPrefs.density = density;
  if (await writeSetting(DENSITY, density)) return true;
  taskManagerPrefs.density = before;
  return false;
}

export async function setAccordion(on: boolean): Promise<boolean> {
  if (on === taskManagerPrefs.accordion) return true;
  const before = taskManagerPrefs.accordion;
  taskManagerPrefs.accordion = on;
  if (await writeSetting(ACCORDION, on)) return true;
  taskManagerPrefs.accordion = before;
  return false;
}

export async function setShowTab(on: boolean): Promise<boolean> {
  const before = taskManagerPrefs.showTab;
  taskManagerPrefs.showTab = on;
  if (await writeSetting(SHOW_TAB, on)) return true;
  taskManagerPrefs.showTab = before;
  return false;
}

export async function setShowEmptyGroups(on: boolean): Promise<boolean> {
  const before = taskManagerPrefs.showEmptyGroups;
  taskManagerPrefs.showEmptyGroups = on;
  if (await writeSetting(SHOW_EMPTY_GROUPS, on)) return true;
  taskManagerPrefs.showEmptyGroups = before;
  return false;
}

export async function setBadgeStatus(status: BadgeStatus, on: boolean): Promise<boolean> {
  const before = taskManagerPrefs.badge;
  taskManagerPrefs.badge = { ...before, [status]: on };
  if (await writeSetting(BADGE_SETTING[status], on)) return true;
  taskManagerPrefs.badge = before;
  return false;
}

export function badgeStatuses(): BadgeStatus[] {
  return BADGE_STATUSES.filter((status) => taskManagerPrefs.badge[status]);
}
