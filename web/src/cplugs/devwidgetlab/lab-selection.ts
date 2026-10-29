/* the viewer page */
import { DEFAULT_SIDEBAR_VIEW, SIDEBAR_AREAS, SIDEBAR_DENSITIES, SIDEBAR_WIDTHS, parseScenario, type LabHost, type LabSize, type LabWidget, type SidebarView } from '../sdk/widget-lab';
import { FIXTURE_CHOICES, type FixtureChoice } from './frame-url';
import { sizesToDraw, type CaptureOutcome } from './lab-model';

export const LAB_CHANNEL = 'devwidgetlab.channel';
export const SELECTION_KEY = 'devwidgetlab.selection';
export const FIRST_SIZE = 'm';
export const FIRST_WIDGET = 'core.notes';
export const FALLBACK_THEME = 'carnivore';

export type LabView = 'widget' | 'fit' | 'compare';
export type CompareMode = 'side' | 'draft';

export const DRAWER_DOCKS = ['left', 'bottom', 'right'] as const;
export type DrawerDock = (typeof DRAWER_DOCKS)[number];
/* pop-out window */
export const PLACEMENT_ORDER = ['home', 'terminal', 'left', 'bottom', 'right', 'popout'] as const;
export type Placement = (typeof PLACEMENT_ORDER)[number];

export const isDockPlacement = (placement: Placement): placement is DrawerDock => (DRAWER_DOCKS as readonly string[]).includes(placement);

export const DEFAULT_DOCKS: readonly DrawerDock[] = DRAWER_DOCKS;

export interface FrameRef {
  host: string;
  size: string;
  dock?: DrawerDock;
}

export interface LabSelection {
  widget: string;
  hosts: string[];
  sizes: string[];
  theme: string;
  fixture: FixtureChoice;
  scenario: string | null;
  view: LabView;
  focus: FrameRef | null;
  draft: string | null;
  compare: CompareMode;
  docks: DrawerDock[];
  bandSizes: Record<string, string>;
  /* the real left sidebar */
  sidebar: SidebarView;
}

/* the CHECKS block */
export type CheckScope = 'all' | 'selected';

export interface LabFolds {
  checks: boolean;
  preview: boolean;
  scenario: boolean;
  capture: boolean;
}

export interface LabLive {
  captures: CaptureOutcome[];
  capturing: { done: number; total: number } | null;
  matrixSeq: number;
  menuOpen: boolean;
}

export type LabIntent =
  | { intent: 'pick'; widget: string; host?: string; size?: string }
  | { intent: 'size'; host: string; size: string }
  | { intent: 'sidebar'; view: SidebarView }
  | { intent: 'focus'; focus: FrameRef | null }
  | { intent: 'view'; view: LabView }
  | { intent: 'fixture'; json: string }
  | { intent: 'open-menu' };

/* the PREVIEW block */
export const PREVIEW_WIDTHS_SHOWN = false;

export const DEFAULT_FOLDS: LabFolds = { checks: true, preview: true, scenario: false, capture: true };

export const EMPTY_LIVE: LabLive = { captures: [], capturing: null, matrixSeq: 0, menuOpen: false };

export function declaredZones(widget: LabWidget | undefined): string[] {
  return (widget?.hosts ?? []).filter((host) => host.supported).map((host) => host.zone);
}

export function sizeNames(widget: LabWidget | undefined): string[] {
  const names: string[] = [];
  for (const host of widget?.hosts ?? []) {
    if (!host.supported) continue;
    for (const size of host.sizes) if (!names.includes(size.name)) names.push(size.name);
  }
  return names;
}

/* the PREVIEW block */
export interface SizeOption {
  name: string;
  widths: number[];
  main: boolean;
}

export const MAIN_SIZES: readonly string[] = ['s', 'm', 'l'];

export function sizeOptions(widget: LabWidget | undefined): SizeOption[] {
  const options: SizeOption[] = [];
  for (const host of widget?.hosts ?? []) {
    if (!host.supported) continue;
    for (const size of host.sizes) {
      const found = options.find((one) => one.name === size.name);
      const main = MAIN_SIZES.includes(size.name);
      if (!found) options.push({ name: size.name, widths: [size.w], main });
      else {
        if (!found.widths.includes(size.w)) found.widths.push(size.w);
        found.main = found.main || main;
      }
    }
  }
  return options.map((one) => ({ ...one, widths: [...one.widths].sort((a, b) => a - b) }));
}

export function selectWidget(sel: LabSelection, widget: LabWidget | undefined): LabSelection {
  if (!widget) return sel;
  const names = sizeNames(widget);
  const kept = sel.sizes.filter((name) => names.includes(name));
  const fallback = names.includes(FIRST_SIZE) ? FIRST_SIZE : names[0];
  const sizes = kept.length > 0 ? kept : fallback ? [fallback] : [FIRST_SIZE];
  const hosts = declaredZones(widget);
  return { ...sel, widget: widget.key, hosts: hosts.length > 0 ? hosts : sel.hosts, docks: [...DEFAULT_DOCKS], sizes, view: 'widget', focus: null, draft: null };
}

export function flipIn(list: readonly string[], name: string): string[] {
  if (!list.includes(name)) return [...list, name];
  return list.length > 1 ? list.filter((one) => one !== name) : [...list];
}

export function defaultSelection(widgets: readonly LabWidget[], theme: string): LabSelection {
  const widget = widgets.find((one) => one.key === FIRST_WIDGET) ?? widgets[0];
  const base: LabSelection = { widget: widget?.key ?? '', hosts: [], sizes: [FIRST_SIZE], theme, fixture: 'data', scenario: null, view: 'widget', focus: null, draft: null, compare: 'side', docks: [...DEFAULT_DOCKS], bandSizes: {}, sidebar: { ...DEFAULT_SIDEBAR_VIEW } };
  return selectWidget(base, widget);
}

function names(value: unknown): value is string[] {
  return Array.isArray(value) && value.length > 0 && value.every((one) => typeof one === 'string' && one !== '');
}

export function docksOf(raw: unknown, old: unknown): DrawerDock[] {
  const known = (value: unknown): value is DrawerDock => DRAWER_DOCKS.includes(value as DrawerDock);
  if (Array.isArray(raw)) {
    const kept = DRAWER_DOCKS.filter((one) => raw.includes(one));
    if (kept.length > 0) return kept;
  } else if (known(old) && old !== 'left') {
    return [old];
  }
  return [...DEFAULT_DOCKS];
}

export function placementsOn(sel: Pick<LabSelection, 'hosts' | 'docks'>): Placement[] {
  return PLACEMENT_ORDER.filter((one) => (isDockPlacement(one) ? sel.hosts.includes('drawer') && sel.docks.includes(one) : sel.hosts.includes(one)));
}

export function flipPlacement(sel: Pick<LabSelection, 'hosts' | 'docks'>, placement: Placement): { hosts: string[]; docks: DrawerDock[] } {
  const on = placementsOn(sel);
  const keep = { hosts: [...sel.hosts], docks: [...sel.docks] };
  if (on.includes(placement) && on.length === 1) return keep;
  if (!isDockPlacement(placement)) return { hosts: on.includes(placement) ? sel.hosts.filter((zone) => zone !== placement) : [...sel.hosts, placement], docks: keep.docks };
  const drawerOn = sel.hosts.includes('drawer');
  const docks = on.includes(placement) ? sel.docks.filter((one) => one !== placement) : [...(drawerOn ? sel.docks : []), placement];
  const ordered = DRAWER_DOCKS.filter((one) => docks.includes(one));
  const hosts = ordered.length === 0 ? sel.hosts.filter((zone) => zone !== 'drawer') : drawerOn ? [...sel.hosts] : [...sel.hosts, 'drawer'];
  return { hosts, docks: ordered };
}

function bandSizesOf(raw: unknown, zones: readonly string[]): Record<string, string> {
  if (typeof raw !== 'object' || raw === null || Array.isArray(raw)) return {};
  return Object.fromEntries(Object.entries(raw).filter(([zone, name]) => zones.includes(zone) && typeof name === 'string' && name !== '')) as Record<string, string>;
}

export function bandSize(host: LabHost, sel: LabSelection): LabSize | null {
  return host.sizes.find((size) => size.name === sel.bandSizes[host.zone]) ?? sizesToDraw(host, sel.sizes)[0] ?? null;
}

export function normalizeSelection(raw: unknown, widgets: readonly LabWidget[], theme: string): LabSelection {
  const base = defaultSelection(widgets, theme);
  if (typeof raw !== 'object' || raw === null) return base;
  const got = raw as Record<string, unknown>;
  const widget = widgets.find((one) => one.key === got['widget']);
  if (!widget) return base;
  const zones = declaredZones(widget);
  const hosts = names(got['hosts']) ? got['hosts'].filter((zone) => zones.includes(zone)) : [];
  const focus = got['focus'] as Partial<FrameRef> | null | undefined;
  return {
    widget: widget.key,
    hosts: hosts.length > 0 ? hosts : zones.length > 0 ? zones : base.hosts,
    sizes: names(got['sizes']) ? got['sizes'] : selectWidget({ ...base, sizes: [FIRST_SIZE] }, widget).sizes,
    theme: typeof got['theme'] === 'string' && got['theme'] !== '' ? got['theme'] : theme,
    fixture: FIXTURE_CHOICES.includes(got['fixture'] as FixtureChoice) ? (got['fixture'] as FixtureChoice) : 'data',
    scenario: typeof got['scenario'] === 'string' ? got['scenario'] : null,
    view: got['view'] === 'fit' ? 'fit' : got['view'] === 'compare' && typeof got['draft'] === 'string' ? 'compare' : 'widget',
    draft: typeof got['draft'] === 'string' && got['draft'] !== '' ? got['draft'] : null,
    compare: got['compare'] === 'draft' ? 'draft' : 'side',
    docks: docksOf(got['docks'], got['dock']),
    bandSizes: bandSizesOf(got['bandSizes'], zones),
    sidebar: sidebarOf(got['sidebar']),
    focus: focus && typeof focus.host === 'string' && typeof focus.size === 'string'
      ? { host: focus.host, size: focus.size, ...(DRAWER_DOCKS.includes(focus.dock as DrawerDock) ? { dock: focus.dock as DrawerDock } : {}) }
      : null,
  };
}

export function sidebarOf(raw: unknown): SidebarView {
  const got = (typeof raw === 'object' && raw !== null ? raw : {}) as Record<string, unknown>;
  const pick = <T extends string>(value: unknown, allowed: readonly T[], fallback: T): T => ((allowed as readonly unknown[]).includes(value) ? (value as T) : fallback);
  return {
    width: pick(got['width'], SIDEBAR_WIDTHS, DEFAULT_SIDEBAR_VIEW.width),
    folded: got['folded'] === true,
    area: pick(got['area'], SIDEBAR_AREAS, DEFAULT_SIDEBAR_VIEW.area),
    density: pick(got['density'], SIDEBAR_DENSITIES, DEFAULT_SIDEBAR_VIEW.density),
  };
}

export function normalizeFolds(raw: unknown): LabFolds {
  const got = (typeof raw === 'object' && raw !== null ? raw : {}) as Record<string, unknown>;
  const pick = <K extends keyof LabFolds>(key: K): LabFolds[K] => (typeof got[key] === 'boolean' ? (got[key] as LabFolds[K]) : DEFAULT_FOLDS[key]);
  return { checks: pick('checks'), preview: pick('preview'), scenario: pick('scenario'), capture: pick('capture') };
}

export function framesOnShow(widget: LabWidget | undefined, sel: LabSelection): FrameRef[] {
  const all = (widget?.hosts ?? [])
    .filter((host: LabHost) => host.supported && sel.hosts.includes(host.zone))
    .flatMap((host): FrameRef[] => {
      const size = bandSize(host, sel);
      if (!size) return [];
      return host.zone === 'drawer' ? sel.docks.map((dock) => ({ host: host.zone, size: size.name, dock })) : [{ host: host.zone, size: size.name }];
    });
  const focus = sel.focus;
  const same = (one: FrameRef): boolean => focus !== null && one.host === focus.host && one.size === focus.size && one.dock === focus.dock;
  return focus && all.some(same) ? [focus] : all;
}

export function applyIntent(sel: LabSelection, intent: LabIntent, widgets: readonly LabWidget[]): LabSelection {
  if (intent.intent === 'view') return { ...sel, view: intent.view };
  if (intent.intent === 'focus') return { ...sel, focus: intent.focus };
  if (intent.intent === 'sidebar') return { ...sel, sidebar: sidebarOf(intent.view) };
  if (intent.intent === 'size') {
    const published = widgets.find((one) => one.key === sel.widget)?.hosts.find((host) => host.zone === intent.host)?.sizes.some((size) => size.name === intent.size);
    if (!published) return sel;
    return { ...sel, bandSizes: { ...sel.bandSizes, [intent.host]: intent.size }, focus: sel.focus?.host === intent.host ? null : sel.focus };
  }
  if (intent.intent !== 'pick') return sel;
  const widget = widgets.find((one) => one.key === intent.widget);
  if (!widget) return sel;
  const next = selectWidget(sel, widget);
  if (!intent.host) return next;
  const zones = declaredZones(widget);
  if (!zones.includes(intent.host)) return next;
  const size = intent.size && sizeNames(widget).includes(intent.size) ? intent.size : null;
  return {
    ...next,
    hosts: next.hosts.includes(intent.host) ? next.hosts : [...next.hosts, intent.host],
    bandSizes: size ? { ...next.bandSizes, [intent.host]: size } : next.bandSizes,
    focus: size ? { host: intent.host, size, ...(intent.host === 'drawer' && sel.docks[0] ? { dock: sel.docks[0] } : {}) } : null,
  };
}

export function appliedRoutes(scenario: string | null): number {
  const parsed = scenario === null ? null : parseScenario(scenario);
  return parsed?.ok ? parsed.routes : 0;
}
