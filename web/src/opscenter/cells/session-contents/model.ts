import type { ContentsItem, ContentsSection, SessionContents } from './types';

const PREFIX = 'opscenter.cell.session_contents';

export const kindKey = (kind: string): string => `${PREFIX}.kind.${kind}`;

export const scopeKey = (scope: string): string => `${PREFIX}.scope.${scope}`;

const REFUSAL_KEYS: Readonly<Record<string, string>> = {
  remote_host: `${PREFIX}.refused.remote_host`,
  unsupported_family: `${PREFIX}.refused.unsupported_family`,
  session_not_found: `${PREFIX}.refused.session_not_found`,
};

export function refusalKey(code: string | null): string {
  return (code && REFUSAL_KEYS[code]) || `${PREFIX}.error`;
}

export function totalItems(data: SessionContents | null): number | null {
  return data ? data.sections.reduce((sum, one) => sum + one.items.length, 0) : null;
}

export const SCOPE_OPTION = 'scope';

export const SCOPES = ['local', 'global', 'all'] as const;

export type ScopeFilter = (typeof SCOPES)[number];

export const DEFAULT_SCOPE: ScopeFilter = 'all';

export const SCOPE_ICONS: Readonly<Record<ScopeFilter, string>> = { local: 'folder', global: 'globe', all: 'list' };

const ITEM_SCOPE_ICONS: Readonly<Record<string, string>> = { project: 'folder', global: 'globe', plugin: 'plug' };

export const itemScopeIcon = (scope: string): string => ITEM_SCOPE_ICONS[scope] ?? 'globe';

export const EMPTY_OPTION = 'show_empty';

export const DEFAULT_SHOW_EMPTY = true;

export function showEmptyOf(value: unknown): boolean {
  return typeof value === 'boolean' ? value : DEFAULT_SHOW_EMPTY;
}

export function scopeFilterOf(value: unknown): ScopeFilter {
  return SCOPES.find((one) => one === value) ?? DEFAULT_SCOPE;
}

export function inScope(itemScope: string, filter: ScopeFilter): boolean {
  if (filter === 'all') return true;
  return filter === 'local' ? itemScope === 'project' : itemScope !== 'project';
}

export const itemKey = (kind: string, one: ContentsItem): string => `${kind}:${one.scope}:${one.name}:${one.path ?? ''}`;

export function visibleItems(items: readonly ContentsItem[], filter: ScopeFilter, text: string): ContentsItem[] {
  const needle = text.trim().toLowerCase();
  return items.filter((one) => inScope(one.scope, filter)
    && (!needle || `${one.name}\n${one.path ?? ''}\n${one.description}`.toLowerCase().includes(needle)));
}

export interface ShownSection {
  section: ContentsSection;
  items: ContentsItem[];
}

export function shownSections(sections: readonly ContentsSection[], filter: ScopeFilter, text: string, showEmpty: boolean): ShownSection[] {
  return sections
    .map((section) => ({ section, items: visibleItems(section.items, filter, text) }))
    .filter((one) => showEmpty || one.items.length > 0);
}

export function accountOf(configDir: string): string {
  const name = configDir.replace(/\/+$/, '').split('/').pop() ?? '';
  return !name || name.startsWith('.') ? 'default' : name;
}

export const statusKey = (status: string): string => `${PREFIX}.status.${status}`;

export const kindOneKey = (kind: string): string => `${PREFIX}.kind_one.${kind}`;

export function detailBeyondLines(one: ContentsItem): string {
  const text = one.description || one.detail || '';
  return one.lines === null ? text : text.replace(/^\d+ lines?(, )?/, '');
}

export const CONTROLS_HEAD_MIN_WIDTH = 320;
