import { viewFilterActive } from './task-manager-view-filter.svelte';
import { DEFAULT_FOLDED, SECTION_ORDER, type TaskManagerSectionKey } from './task-manager-status-sections';

export const FOLDS_KEY = 'cloude.huddle.statusFolds';

export function subFoldKey(area: number | null, section: TaskManagerSectionKey): string {
  return `${area ?? 'none'}:${section}`;
}

const STATUS_SUB_PREFIX = 'status/';

export function statusSubFoldKey(area: number | null, section: TaskManagerSectionKey, list = ''): string {
  return `${STATUS_SUB_PREFIX}${area === null ? `${list}/` : ''}${subFoldKey(area, section)}`;
}

export function sectionFoldKey(list: string, section: TaskManagerSectionKey): string {
  return `${list}/${section}`;
}

export function projectFoldKey(list: string): string {
  return `project/${list}`;
}

function folds(key: string): boolean {
  if (key.startsWith(STATUS_SUB_PREFIX)) return false;
  const section = key.slice(Math.max(key.lastIndexOf(':'), key.lastIndexOf('/')) + 1);
  return (DEFAULT_FOLDED as readonly string[]).includes(section);
}

export const RETIRED_SECTIONS: Readonly<Record<string, TaskManagerSectionKey>> = Object.freeze({ back_burner: 'todo', waiting_install: 'waiting' });

export function currentFoldKey(key: string): string {
  const cut = Math.max(key.lastIndexOf(':'), key.lastIndexOf('/')) + 1;
  const renamed = RETIRED_SECTIONS[key.slice(cut)];
  return renamed === undefined ? key : key.slice(0, cut) + renamed;
}

function renamed(choices: Record<string, boolean>): Record<string, boolean> {
  const out: Record<string, boolean> = {};
  for (const [key, folded] of Object.entries(choices)) {
    const now = currentFoldKey(key);
    if (now === key || !(now in choices)) out[now] = folded;
  }
  return out;
}

function load(): Record<string, boolean> {
  try {
    const raw = globalThis.localStorage?.getItem(FOLDS_KEY);
    if (raw === null || raw === undefined) return {};
    const parsed: unknown = JSON.parse(raw);
    if (Array.isArray(parsed)) {
      const names = parsed.map((k) => (typeof k === 'string' ? currentFoldKey(k) : k));
      return Object.fromEntries(SECTION_ORDER.map((k) => [k, names.includes(k)]));
    }
    if (parsed === null || typeof parsed !== 'object') return {};
    const stored = Object.fromEntries(Object.entries(parsed).filter(([, v]) => typeof v === 'boolean')) as Record<string, boolean>;
    const choices = renamed(stored);
    if (Object.keys(stored).some((key) => currentFoldKey(key) !== key)) globalThis.localStorage?.setItem(FOLDS_KEY, JSON.stringify(choices));
    return choices;
  } catch {
    return {};
  }
}

export const statusFolds = $state<{ choices: Record<string, boolean> }>({ choices: load() });

export function isFolded(key: string): boolean {
  if (viewFilterActive()) return false;
  return statusFolds.choices[key] ?? folds(key);
}

export function setSectionsFolded(keys: readonly string[], folded: boolean): void {
  if (!keys.length) return;
  statusFolds.choices = { ...statusFolds.choices, ...Object.fromEntries(keys.map((key) => [key, folded])) };
  try {
    globalThis.localStorage?.setItem(FOLDS_KEY, JSON.stringify(statusFolds.choices));
  } catch {
  }
}

export function setSectionFolded(key: string, folded: boolean): void {
  setSectionsFolded([key], folded);
}

export const ACCORDION_OPEN_KEY = 'cloude.huddle.accordionOpen';

function loadAccordionOpen(): string | null {
  try {
    const raw = globalThis.localStorage?.getItem(ACCORDION_OPEN_KEY);
    return typeof raw === 'string' && raw !== '' ? raw : null;
  } catch {
    return null;
  }
}

function saveAccordionOpen(key: string | null): void {
  try {
    if (key === null) globalThis.localStorage?.removeItem(ACCORDION_OPEN_KEY);
    else globalThis.localStorage?.setItem(ACCORDION_OPEN_KEY, key);
  } catch {
  }
}

const rememberedOpen = loadAccordionOpen();
export const accordionState = $state<{ open: string | null; chosen: boolean }>({ open: rememberedOpen, chosen: rememberedOpen !== null });

export function accordionOpenKey(projects: readonly string[]): string | null {
  if (accordionState.chosen && (accordionState.open === null || projects.includes(accordionState.open))) return accordionState.open;
  return projects.find((key) => !isFolded(key)) ?? projects[0] ?? null;
}

export function accordionToggle(projects: readonly string[], key: string): void {
  const open = accordionOpenKey(projects);
  if (open === key) return;
  accordionState.open = key;
  accordionState.chosen = true;
  saveAccordionOpen(key);
}

export function resetAccordion(): void {
  accordionState.open = null;
  accordionState.chosen = false;
  saveAccordionOpen(null);
}

export function reloadAccordion(): void {
  const open = loadAccordionOpen();
  accordionState.open = open;
  accordionState.chosen = open !== null;
}

export function reloadStatusFolds(): void {
  statusFolds.choices = load();
}

export const HIDDEN_SECTIONS_KEY = 'cloude.huddle.hiddenSections';

/*  hidden  */
function loadHiddenSections(): TaskManagerSectionKey[] {
  try {
    const parsed: unknown = JSON.parse(globalThis.localStorage?.getItem(HIDDEN_SECTIONS_KEY) ?? '[]');
    if (!Array.isArray(parsed)) return [];
    const names = parsed.map((k) => (typeof k === 'string' ? (RETIRED_SECTIONS[k] ?? k) : k));
    return SECTION_ORDER.filter((key) => names.includes(key));
  } catch {
    return [];
  }
}

/*  hidden  */
export const hiddenSections = $state<{ keys: TaskManagerSectionKey[] }>({ keys: loadHiddenSections() });

export function isSectionHidden(key: TaskManagerSectionKey): boolean {
  return hiddenSections.keys.includes(key);
}

export function setSectionHidden(key: TaskManagerSectionKey, hidden: boolean): void {
  hiddenSections.keys = SECTION_ORDER.filter((k) => (k === key ? hidden : hiddenSections.keys.includes(k)));
  try {
    globalThis.localStorage?.setItem(HIDDEN_SECTIONS_KEY, JSON.stringify(hiddenSections.keys));
  } catch {
  }
}

/*  hidden  */
export function reloadHiddenSections(): void {
  hiddenSections.keys = loadHiddenSections();
}

/*  hidden  */
export const COUNTS_HIDDEN_KEY = 'cloude.huddle.countsHidden';

function loadCountsHidden(): boolean {
  try {
    return globalThis.localStorage?.getItem(COUNTS_HIDDEN_KEY) === 'off';
  } catch {
    return false;
  }
}

/*  hidden  */
export const countBadges = $state<{ hidden: boolean }>({ hidden: loadCountsHidden() });

export function setCountsHidden(hidden: boolean): void {
  countBadges.hidden = hidden;
  try {
    if (hidden) globalThis.localStorage?.setItem(COUNTS_HIDDEN_KEY, 'off');
    else globalThis.localStorage?.removeItem(COUNTS_HIDDEN_KEY);
  } catch {
  }
}

export function reloadCountsHidden(): void {
  countBadges.hidden = loadCountsHidden();
}
