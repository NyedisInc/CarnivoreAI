
import { PRIMARY_SLOT, resetLayout } from './model';
import { clear, flushSave, load, save, type LoadResult } from './persist';
import type { Layout, MetaMap } from './types';
import { META } from './meta';

export const SESSION_INDEX_KEY = 'cloudecode.opscenter.layout.terminal.sessions.v1';

export const MAX_SESSION_LAYOUTS = 32;

export function layoutKey(name: string, epoch: number | null): string {
  return epoch === null ? name : `${name}:${epoch}`;
}

export const LAYOUT_KEY_PREFIX = 'layout:';

export function isLayoutKey(key: string): boolean {
  return typeof key === 'string' && key.startsWith(LAYOUT_KEY_PREFIX);
}

function storage(): Storage | null {
  try {
    const store = globalThis.localStorage;
    if (!store) return null;
    store.getItem(SESSION_INDEX_KEY);
    return store;
  } catch {
    return null;
  }
}

export function readIndex(): string[] {
  const store = storage();
  if (!store) return [];
  try {
    const raw: unknown = JSON.parse(store.getItem(SESSION_INDEX_KEY) ?? '[]');
    if (!Array.isArray(raw)) return [];
    return [...new Set(raw.filter((one): one is string => typeof one === 'string' && one !== ''))];
  } catch {
    return [];
  }
}

function writeIndex(names: string[]): void {
  const store = storage();
  if (!store) return;
  try {
    if (names.length === 0) store.removeItem(SESSION_INDEX_KEY);
    else store.setItem(SESSION_INDEX_KEY, JSON.stringify(names));
  } catch {
  }
}

export function touchSession(name: string): string[] {
  if (!name) return [];
  const names = [name, ...readIndex().filter((one) => one !== name)];
  const evicted = names.slice(MAX_SESSION_LAYOUTS);
  for (const gone of evicted) clear('terminal', gone);
  writeIndex(names.slice(0, MAX_SESSION_LAYOUTS));
  return evicted;
}

export function forgetSession(name: string): void {
  if (!name) return;
  clear('terminal', name);
  const names = readIndex();
  if (names.includes(name)) writeIndex(names.filter((one) => one !== name));
}

/*  hidden  */
export function isBareTerminal(layout: Layout): boolean {
  const base = resetLayout(META, 'terminal');
  const [row] = layout.rows;
  if (layout.rows.length !== 1 || !row || row.slots.length !== 1) return false;
  if (row.slots[0]?.id !== PRIMARY_SLOT || (row.slots[0]?.span ?? 1) > 1) return false;
  if (layout.collapsed.length !== 0) return false;
  const hidden = [...layout.hidden].sort();
  const wanted = [...base.hidden].sort();
  return hidden.length === wanted.length && hidden.every((id, at) => id === wanted[at]);
}

export function openSessionLayout(name: string, epoch: number | null = null, metas: MetaMap = META): LoadResult {
  const key = layoutKey(name, epoch);
  const own = load(metas, 'terminal', '', key);
  if (own.stored || own.notice) return own;
  if (key !== name) {
    const named = load(metas, 'terminal', '', name);
    if (named.stored) {
      forgetSession(name);
      save(named.layout, 'terminal', key);
      flushSave('terminal', key);
      touchSession(key);
      return named;
    }
  }
  const legacy = load(metas, 'terminal', '');
  if (!legacy.stored) return legacy.notice ? { ...own, notice: legacy.notice } : own;
  clear('terminal');
  if (isBareTerminal(legacy.layout)) return own;
  save(legacy.layout, 'terminal', key);
  flushSave('terminal', key);
  touchSession(key);
  return { ...legacy, stored: true };
}
