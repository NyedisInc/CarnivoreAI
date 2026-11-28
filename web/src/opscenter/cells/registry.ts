
import type { Component } from 'svelte';
import { SvelteMap } from 'svelte/reactivity';
import { META } from '../engine/meta';
import { openFeatures, openLedger, openThemes } from '../api';
import { openSessionsScreen } from '../../lib/sessions-page/screen-host';
import { kindOf } from '../engine/meta';
import type { CellId, CellMeta, InstanceKind, PhoneSummary, SlotId } from '../engine/types';
import type { PlacementOptions } from '../widgets/placement-options';
import StatTile from './stat-tile/Cell.svelte';
import { STAT_TILE_IDS } from '../engine/stat-tile-meta';
import RunningSessions from './running-sessions/Cell.svelte';
import ClosedSessions from './closed-sessions/Cell.svelte';
import Projects from './projects/Cell.svelte';
import Skills from './skills/Cell.svelte';
import Plugins from './plugins/Cell.svelte';
import Themes from './themes/Cell.svelte';
import Ledger from './ledger/Cell.svelte';
import ActivityLog from './activity-log/Cell.svelte';
import Notes from './notes/Cell.svelte';
import Files from './files/Cell.svelte';
import TerminalCell from './terminal/Cell.svelte';
import BrowserCell from './browser/Cell.svelte';
import AnalyticsCell from './analytics/Cell.svelte';
import ScheduledTasks from './scheduled-tasks/Cell.svelte';
import { titleCount as scheduledCount, phoneTotal as scheduledTotal } from './scheduled-tasks/meta';
import KeepAwake from './keep-awake/Cell.svelte';
import WarRoom from './warroom/Cell.svelte';
import MachineStats from './machine-stats/Cell.svelte';
import Changes from './changes/Cell.svelte';
import Shell from './shell/Cell.svelte';
import Crosstalk from './crosstalk/Cell.svelte';
import Tasks from './tasks/Cell.svelte';
import TasksAll from './tasks-all/Cell.svelte';
import Automations from './automations/Cell.svelte';
import AutomationsAll from './automations-all/Cell.svelte';
import Timeline from './timeline/Cell.svelte';
import Pipeline from './pipeline/Cell.svelte';
import Bookmarks from './bookmarks/Cell.svelte';
import BookmarksAll from './bookmarks-all/Cell.svelte';
import { titleCount as keepAwakeCount, phoneTotal as keepAwakeTotal } from './keep-awake/meta';
import Questions from './questions/Cell.svelte';
import Developer from './developer/Cell.svelte';
import SessionContents from './session-contents/Cell.svelte';
import { titleCount as sessionContentsCount, phoneTotal as sessionContentsTotal } from './session-contents/meta';
import { titleCount as questionsCount, phoneTotal as questionsTotal } from './questions/meta';

import { titleCount as runningCount, phoneSummary as runningSummary, phoneTotal as runningTotal } from './running-sessions/meta';
import {
  titleCount as closedCount,
  phoneSummary as closedSummary,
  phoneTotal as closedTotal,
} from './closed-sessions/meta';
import { titleCount as projectsCount, phoneTotal as projectsTotal } from './projects/meta';
import {
  titleCount as skillsCount,
  titleSuffix as skillsSuffix,
  onRightControl as skillsRefresh,
  phoneTotal as skillsTotal,
} from './skills/meta';
import { titleCount as pluginsCount, phoneTotal as pluginsTotal } from './plugins/meta';
import { titleCount as themesCount, phoneSummary as themesSummary } from './themes/meta';
import { titleCount as ledgerCount, phoneSummary as ledgerSummary, phoneTotal as ledgerTotal } from './ledger/meta';
import {
  titleSuffix as activitySuffix,
  onRightControl as activityClear,
  phoneSummary as activitySummary,
  phoneTotal as activityTotal,
} from './activity-log/meta';

export interface CellBinding {
  component: Component<any>;
  /* could not be determined */
  count?: () => number | null;
  countFor?: (options?: PlacementOptions) => number | null;
  suffix?: () => string | null;
  onRightControl?: () => void;
  phoneSummary?: () => PhoneSummary | null;
  phoneTotal?: () => number | null;
}

export interface RegisteredCell extends CellBinding {
  meta: CellMeta;
}

export const PLUGIN_CELL_IDS = ['task-manager-mk2', 'task-manager-mk2-all'] as const;

export type PluginCellId = (typeof PLUGIN_CELL_IDS)[number];

export const REGISTRY: Readonly<Record<Exclude<CellId, PluginCellId>, RegisteredCell>> = {
  ...(Object.fromEntries(STAT_TILE_IDS.map((id) => [id, { meta: META[id], component: StatTile }])) as Record<
    (typeof STAT_TILE_IDS)[number],
    RegisteredCell
  >),
  'running-sessions': {
    meta: META['running-sessions'],
    component: RunningSessions,
    count: runningCount,
    phoneSummary: runningSummary,
    phoneTotal: runningTotal,
    onRightControl: () => void openSessionsScreen(),
  },
  'closed-sessions': {
    meta: META['closed-sessions'],
    component: ClosedSessions,
    count: closedCount,
    phoneSummary: closedSummary,
    phoneTotal: closedTotal,
    onRightControl: () => void openSessionsScreen(),
  },
  projects: {
    meta: META.projects,
    component: Projects,
    count: projectsCount,
    phoneTotal: projectsTotal,
    onRightControl: () => void openSessionsScreen(),
  },
  skills: {
    meta: META.skills,
    component: Skills,
    count: skillsCount,
    suffix: skillsSuffix,
    onRightControl: skillsRefresh,
    phoneTotal: skillsTotal,
  },
  plugins: {
    meta: META.plugins,
    component: Plugins,
    count: pluginsCount,
    phoneTotal: pluginsTotal,
    onRightControl: () => void openFeatures(),
  },
  themes: {
    meta: META.themes,
    component: Themes,
    count: themesCount,
    phoneSummary: themesSummary,
    onRightControl: () => void openThemes(),
  },
  ledger: {
    meta: META.ledger,
    component: Ledger,
    count: ledgerCount,
    phoneSummary: ledgerSummary,
    phoneTotal: ledgerTotal,
    onRightControl: () => void openLedger(),
  },
  'activity-log': {
    meta: META['activity-log'],
    component: ActivityLog,
    suffix: activitySuffix,
    onRightControl: activityClear,
    phoneSummary: activitySummary,
    phoneTotal: activityTotal,
  },
  notes: { meta: META.notes, component: Notes },
  files: { meta: META.files, component: Files },
  'scheduled-tasks': {
    meta: META['scheduled-tasks'],
    component: ScheduledTasks,
    count: scheduledCount,
    phoneTotal: scheduledTotal,
  },
  'keep-awake': {
    meta: META['keep-awake'],
    component: KeepAwake,
    count: keepAwakeCount,
    phoneTotal: keepAwakeTotal,
  },
  warroom: { meta: META.warroom, component: WarRoom },
  'machine-stats': { meta: META['machine-stats'], component: MachineStats },
  changes: { meta: META.changes, component: Changes },
  // the Task Manager
  crosstalk: { meta: META.crosstalk, component: Crosstalk },
  tasks: { meta: META.tasks, component: Tasks },
  'tasks-all': { meta: META['tasks-all'], component: TasksAll },
  automations: { meta: META.automations, component: Automations },
  'automations-all': { meta: META['automations-all'], component: AutomationsAll },
  shell: { meta: META.shell, component: Shell },
  timeline: { meta: META.timeline, component: Timeline },
  bookmarks: { meta: META.bookmarks, component: Bookmarks },
  'bookmarks-all': { meta: META['bookmarks-all'], component: BookmarksAll },
  pipeline: { meta: META.pipeline, component: Pipeline },
  // waiting on you
  questions: {
    meta: META.questions,
    component: Questions,
    count: questionsCount,
    phoneTotal: questionsTotal,
  },
  'session-contents': {
    meta: META['session-contents'],
    component: SessionContents,
    count: sessionContentsCount,
    phoneTotal: sessionContentsTotal,
  },
  developer: { meta: META.developer, component: Developer },
};

export const INSTANCE_REGISTRY: Readonly<Partial<Record<InstanceKind, CellBinding>>> = {
  terminal: { component: TerminalCell },
  browser: { component: BrowserCell },
  analytics: { component: AnalyticsCell },
};

/* the Task Manager */
const PLUGIN_CELLS = new SvelteMap<PluginCellId, RegisteredCell>();

export function registerPluginCell(id: PluginCellId, component: Component<any>): void {
  PLUGIN_CELLS.set(id, { meta: META[id], component });
}

const PLUGIN_BINDINGS = new Map<InstanceKind, CellBinding>();

export function registerPluginBinding(kind: InstanceKind, binding: CellBinding): void {
  PLUGIN_BINDINGS.set(kind, binding);
}

export function unregisterPluginBinding(kind: string): boolean {
  return PLUGIN_BINDINGS.delete(kind as InstanceKind);
}

export function entryFor(slotId: SlotId): CellBinding | undefined {
  const kind = kindOf(slotId);
  if (kind) return INSTANCE_REGISTRY[kind] ?? PLUGIN_BINDINGS.get(kind);
  const id = slotId as CellId;
  return (REGISTRY as Partial<Record<CellId, RegisteredCell>>)[id] ?? PLUGIN_CELLS.get(id as PluginCellId);
}

export function registeredInstanceKinds(): InstanceKind[] {
  return [...(Object.keys(INSTANCE_REGISTRY) as InstanceKind[]).filter((kind) => INSTANCE_REGISTRY[kind] !== undefined), ...PLUGIN_BINDINGS.keys()];
}
