
import { STAT_TILE_IDS, type StatTileId } from '../engine/stat-tile-meta';
import { ANALYTICS_META, BROWSER_META, CELL_IDS, META, TERMINAL_META, kindOf } from '../engine/meta';
import { isPluginSlot } from '../engine/plugin-kinds';
import { resetLayout } from '../engine/model';
import type { CellId, CellMeta, InstanceKind, PluginKind, SlotId } from '../engine/types';
import { fitsFor } from './fits';
import { validateManifest } from './validate';
import {
  WIDGET_CANVASES,
  type WidgetCanvas,
  type WidgetCapability,
  type WidgetCategory,
  type WidgetType,
  type WidgetLooks,
  type WidgetManifest,
  type WidgetSettingsSchema,
  type WidgetView,
} from './types';

export const CORE_WIDGET_VERSION = '1.0.0';

const DRAFT_WIDGET_VERSION = '0.0.0';

const CORE_NAMESPACE = 'core';

export interface CoreExtras {
  category: WidgetCategory;
  type: WidgetType;
  capabilities: readonly WidgetCapability[];
  keepAlive?: 'host';
  scope?: 'session';
  looks?: WidgetLooks;
  views?: readonly WidgetView[];
  viewOf?: string;
  remembers?: readonly string[];
  settings?: WidgetSettingsSchema;
}

const ACTIVITY_LOG_SETTINGS: WidgetSettingsSchema = {
  version: 1,
  fields: {
    showSystem: {
      kind: 'boolean',
      labelKey: 'widgets.setting.activity_log.show_system',
      hintKey: 'widgets.setting.activity_log.show_system.hint',
      default: true,
    },
  },
  groups: [{ labelKey: 'widgets.setting.activity_log.group.show', fields: ['showSystem'] }],
};

const BOOKMARKS_SETTINGS: WidgetSettingsSchema = {
  version: 1,
  fields: {
    showPreview: {
      kind: 'boolean',
      labelKey: 'widgets.setting.bookmarks.show_preview',
      hintKey: 'widgets.setting.bookmarks.show_preview.hint',
      default: true,
    },
    previewTurns: {
      kind: 'number',
      labelKey: 'widgets.setting.bookmarks.preview_turns',
      hintKey: 'widgets.setting.bookmarks.preview_turns.hint',
      default: 4,
      min: 1,
      max: 20,
    },
  },
  groups: [{ labelKey: 'widgets.setting.bookmarks.group.preview', fields: ['showPreview', 'previewTurns'] }],
};

const ALERT_BADGE_FIELD = {
  kind: 'boolean',
  labelKey: 'widgets.setting.alert_badge.show',
  hintKey: 'widgets.setting.alert_badge.show.hint',
  default: true,
} as const;

const FILES_SETTINGS: WidgetSettingsSchema = {
  version: 1,
  fields: {
    showGlobalFolder: {
      kind: 'boolean',
      labelKey: 'widgets.setting.files.show_global_folder',
      hintKey: 'widgets.setting.files.show_global_folder.hint',
      default: true,
    },
    topFolder: {
      kind: 'enum',
      labelKey: 'widgets.setting.files.top_folder',
      hintKey: 'widgets.setting.files.top_folder.hint',
      options: ['global', 'project'],
      default: 'global',
      control: 'segmented',
    },
    showBadge: ALERT_BADGE_FIELD,
  },
  groups: [
    { labelKey: 'widgets.setting.files.group.roots', fields: ['showGlobalFolder', 'topFolder'] },
    { labelKey: 'widgets.setting.alert_badge.group', fields: ['showBadge'] },
  ],
};

const ALERT_BADGE_SETTINGS: WidgetSettingsSchema = {
  version: 1,
  fields: {
    showBadge: ALERT_BADGE_FIELD,
  },
  groups: [{ labelKey: 'widgets.setting.alert_badge.group', fields: ['showBadge'] }],
};

const LEDGER_LOOKS: WidgetLooks = { names: ['compact', 'full'], defaults: { home: 'full', drawer: 'compact' } };

type CoreKind = Exclude<InstanceKind, PluginKind>;

function viewsFor(cell: string): readonly WidgetView[] {
  return [
    { id: 'session', titleKey: 'widget.view.session', widget: `core.${cell}` },
    { id: 'all', titleKey: 'widget.view.all', widget: `core.${cell}-all` },
  ];
}

const TASK_MANAGER_REMEMBERS = ['status-folds', 'open-project', 'hidden-sections', 'counts-hidden', 'swarm-view', 'swarm-inactive', 'schedule-project'] as const;

const EXTRAS: Readonly<Record<CellId | CoreKind, CoreExtras>> = {
  ...(Object.fromEntries(
    STAT_TILE_IDS.map((id): [StatTileId, CoreExtras] => [id, { category: 'overview', type: 'kpi', capabilities: [] }]),
  ) as Record<StatTileId, CoreExtras>),
  'running-sessions': { category: 'sessions', type: 'list', capabilities: ['navigate', 'session-control'] },
  'closed-sessions': { category: 'sessions', type: 'list', capabilities: ['navigate'] },
  projects: { category: 'sessions', type: 'list', capabilities: ['navigate', 'session-control'] },
  skills: { category: 'catalog', type: 'list', capabilities: ['server-write'] },
  plugins: { category: 'catalog', type: 'list', capabilities: [] },
  themes: { category: 'catalog', type: 'list', capabilities: ['navigate', 'server-write'] },
  ledger: { category: 'monitoring', type: 'monitor', capabilities: ['navigate'], looks: LEDGER_LOOKS },
  'activity-log': { category: 'monitoring', type: 'feed', capabilities: [], settings: ACTIVITY_LOG_SETTINGS },
  notes: { category: 'tools', type: 'tool', capabilities: ['server-write'], scope: 'session' },
  files: { category: 'tools', type: 'tool', capabilities: ['navigate', 'server-write'], scope: 'session', settings: FILES_SETTINGS },
  changes: { category: 'tools', type: 'list', capabilities: [], scope: 'session', settings: ALERT_BADGE_SETTINGS },
  'task-manager': { category: 'tools', type: 'feed', capabilities: ['server-write'], scope: 'session', settings: ALERT_BADGE_SETTINGS, views: viewsFor('task-manager'), remembers: TASK_MANAGER_REMEMBERS },
  'task-manager-mk2': { category: 'tools', type: 'feed', capabilities: ['server-write'], scope: 'session', settings: ALERT_BADGE_SETTINGS, views: viewsFor('task-manager-mk2'), remembers: TASK_MANAGER_REMEMBERS },
  'task-manager-mk2-all': { category: 'tools', type: 'feed', capabilities: ['server-write'], settings: ALERT_BADGE_SETTINGS, viewOf: 'core.task-manager-mk2', remembers: TASK_MANAGER_REMEMBERS },
  'task-manager-all': { category: 'tools', type: 'feed', capabilities: ['server-write'], settings: ALERT_BADGE_SETTINGS, viewOf: 'core.task-manager', remembers: TASK_MANAGER_REMEMBERS },
  crosstalk: { category: 'tools', type: 'feed', capabilities: [], scope: 'session' },
  tasks: { category: 'tools', type: 'list', capabilities: [], scope: 'session', settings: ALERT_BADGE_SETTINGS, views: viewsFor('tasks') },
  'tasks-all': { category: 'tools', type: 'list', capabilities: [], settings: ALERT_BADGE_SETTINGS, viewOf: 'core.tasks' },
  automations: { category: 'tools', type: 'list', capabilities: ['server-write'], scope: 'session', views: viewsFor('automations') },
  'automations-all': { category: 'tools', type: 'list', capabilities: ['server-write'], settings: ALERT_BADGE_SETTINGS, viewOf: 'core.automations' },
  timeline: { category: 'tools', type: 'list', capabilities: ['server-write', 'navigate'], scope: 'session' },
  bookmarks: { category: 'tools', type: 'list', capabilities: ['server-write'], scope: 'session', settings: BOOKMARKS_SETTINGS, views: viewsFor('bookmarks') },
  'bookmarks-all': { category: 'tools', type: 'list', capabilities: ['server-write'], viewOf: 'core.bookmarks' },
  pipeline: { category: 'tools', type: 'list', capabilities: [] },
  developer: { category: 'tools', type: 'monitor', capabilities: [] },
  'scheduled-tasks': { category: 'monitoring', type: 'monitor', capabilities: [] },
  'machine-stats': { category: 'monitoring', type: 'monitor', capabilities: [] },
  'keep-awake': { category: 'monitoring', type: 'monitor', capabilities: ['server-write'] },
  // waiting on you
  'task-list': { category: 'tools', type: 'feed', capabilities: ['server-write', 'navigate'], settings: ALERT_BADGE_SETTINGS },
  'session-contents': { category: 'tools', type: 'list', capabilities: [], scope: 'session' },
  warroom: { category: 'monitoring', type: 'monitor', capabilities: [] },
  questions: { category: 'monitoring', type: 'feed', capabilities: ['server-write', 'navigate'], settings: ALERT_BADGE_SETTINGS },
  shell: { category: 'tools', type: 'pane', capabilities: ['terminal-input'], scope: 'session' },
  terminal: {
    category: 'live',
    type: 'pane',
    capabilities: ['navigate', 'session-control', 'terminal-input'],
    keepAlive: 'host',
  },
  browser: { category: 'live', type: 'pane', capabilities: ['browser-control'], keepAlive: 'host' },
  analytics: { category: 'monitoring', type: 'chart', capabilities: ['server-write'] },
};

export function coreWidgetId(key: CellId | InstanceKind): string {
  return `${CORE_NAMESPACE}.${key}`;
}

function singletonCanvases(id: CellId): WidgetCanvas[] {
  return WIDGET_CANVASES.filter((page) => {
    const layout = resetLayout(META, page);
    return layout.hidden.includes(id) || layout.rows.some((row) => row.slots.some((slot) => slot.id === id));
  });
}

function manifestFromMeta(
  key: CellId | InstanceKind,
  meta: CellMeta,
  canvases: readonly WidgetCanvas[],
  instancing: WidgetManifest['instancing'],
  extras: CoreExtras = EXTRAS[key as CellId | CoreKind],
  identity: { id: string; version: string } = { id: coreWidgetId(key), version: CORE_WIDGET_VERSION },
): WidgetManifest {
  const fits = fitsFor(key, meta);
  return {
    id: identity.id,
    version: identity.version,
    titleKey: meta.titleKey,
    icon: meta.icon,
    iconTone: meta.iconTone,
    category: extras.category,
    type: extras.type,
    instancing,
    canvases,
    ...(extras.looks ? { looks: extras.looks } : {}),
    bounds: { minW: meta.minPx, minH: meta.minHeight },
    fits,
    densities: { width: meta.widthStates, height: meta.heightStates },
    capabilities: extras.capabilities,
    ...(extras.settings ? { settings: extras.settings } : {}),
    ...(extras.keepAlive ? { keepAlive: extras.keepAlive } : {}),
    ...(extras.scope ? { scope: extras.scope } : {}),
    ...(extras.views ? { views: extras.views } : {}),
    ...(extras.viewOf ? { viewOf: extras.viewOf } : {}),
    ...(extras.remembers ? { remembers: extras.remembers } : {}),
  };
}

const INSTANCE_BASES: Readonly<Record<CoreKind, CellMeta>> = {
  terminal: TERMINAL_META,
  browser: BROWSER_META,
  analytics: ANALYTICS_META,
};

export const CORE_MANIFESTS: Readonly<Record<string, WidgetManifest>> = Object.freeze(
  Object.fromEntries([
    ...CELL_IDS.map((id) => [coreWidgetId(id), manifestFromMeta(id, META[id], singletonCanvases(id), 'singleton')]),
    ...(Object.keys(INSTANCE_BASES) as CoreKind[]).map((kind) => [
      coreWidgetId(kind),
      manifestFromMeta(kind, INSTANCE_BASES[kind], WIDGET_CANVASES, 'per-target'),
    ]),
  ]),
);

const PLUGIN_MANIFESTS = new Map<string, WidgetManifest>();

export function registerPluginManifest(kind: InstanceKind, meta: CellMeta, extras: CoreExtras, version: string): WidgetManifest {
  const manifest = checked(manifestFromMeta(kind, meta, WIDGET_CANVASES, 'per-target', extras, { id: kind, version: semverOf(version) }));
  PLUGIN_MANIFESTS.set(kind, manifest);
  return manifest;
}

function semverOf(version: string): string {
  const parts = /^(\d+)\.(\d+)(?:\.(\d+))?/.exec(version);
  return parts ? `${parts[1]}.${parts[2]}.${parts[3] ?? '0'}` : '0.0.0';
}

function checked(manifest: WidgetManifest, enforce = true): WidgetManifest {
  const verdict = validateManifest(manifest);
  if (verdict.ok) return manifest;
  console.error('widgets: a manifest was refused', { id: manifest.id, refusal: verdict.refusal, detail: verdict.detail });
  if (enforce) throw new Error(`widget ${manifest.id}: manifest refused (${verdict.refusal}): ${verdict.detail}`);
  return manifest;
}

const DRAFT_MANIFESTS = new Map<string, WidgetManifest>();

export function registerDraftManifest(slot: string, meta: CellMeta, extras: CoreExtras, canvases: readonly WidgetCanvas[]): WidgetManifest {
  const manifest = checked(manifestFromMeta(slot as InstanceKind, meta, canvases, 'singleton', extras, { id: coreWidgetId(slot as CellId), version: DRAFT_WIDGET_VERSION }), false);
  DRAFT_MANIFESTS.set(manifest.id, manifest);
  allTable = null;
  return manifest;
}

let allTable: Readonly<Record<string, WidgetManifest>> | null = null;

export function allManifests(): Readonly<Record<string, WidgetManifest>> {
  allTable ??= Object.freeze({ ...CORE_MANIFESTS, ...Object.fromEntries(DRAFT_MANIFESTS) });
  return allTable;
}

export function manifestById(id: string): WidgetManifest | undefined {
  return CORE_MANIFESTS[id] ?? DRAFT_MANIFESTS.get(id);
}

export function manifestForSlot(slotId: SlotId): WidgetManifest | undefined {
  const key = kindOf(slotId) ?? slotId;
  if (isPluginSlot(key)) return PLUGIN_MANIFESTS.get(key);
  return manifestById(coreWidgetId(key as CellId | InstanceKind));
}
