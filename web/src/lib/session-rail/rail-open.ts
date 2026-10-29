import type { RailEdge } from './rail-model';
import type { SizeStorage } from './rail-size';
import { deviceStorage } from './rail-size';

export type LastUsed = (string | null)[];

export function shownKeys(sections: readonly (readonly string[])[], open: readonly string[], last: LastUsed): string[] {
  if (!open.some((key) => sections.some((section) => section.includes(key)))) return [];
  return sections.flatMap((section, i) => {
    const pick = open.find((key) => section.includes(key)) ?? (last[i] && section.includes(last[i]!) ? last[i]! : section[0]);
    return pick ? [pick] : [];
  });
}

export function pressKey(sections: readonly (readonly string[])[], shown: readonly string[], key: string, last: LastUsed): { open: string[]; last: LastUsed } | null {
  const at = sections.findIndex((section) => section.includes(key));
  if (at < 0) return null;
  if (shown.includes(key)) return { open: [], last: [...last] };
  const next = sections.map((section, i) => {
    if (i === at) return key;
    const out = shown.find((one) => section.includes(one));
    if (out) return out;
    const used = last[i];
    return used && section.includes(used) ? used : (section[0] ?? null);
  });
  const remembered = sections.map((_, i) => next[i] ?? last[i] ?? null);
  return { open: next.filter((one): one is string => one !== null), last: remembered };
}

export function lastUsedKey(edge: RailEdge): string {
  return `carnivore.session.rail.last.${edge}`;
}

export function openKey(edge: RailEdge): string {
  return `carnivore.session.rail.open.${edge}`;
}

export function readOpenKeys(edge: RailEdge, storage: SizeStorage | null = deviceStorage()): string[] {
  if (!storage) return [];
  try {
    const raw = storage.getItem(openKey(edge));
    const list: unknown = raw ? JSON.parse(raw) : [];
    return Array.isArray(list) ? list.filter((one): one is string => typeof one === 'string' && one !== '').slice(0, 2) : [];
  } catch {
    return [];
  }
}

export function writeOpenKeys(edge: RailEdge, keys: readonly string[], storage: SizeStorage | null = deviceStorage()): void {
  if (!storage) return;
  try {
    storage.setItem(openKey(edge), JSON.stringify(keys.slice(0, 2)));
  } catch {
  }
}

export function readLastUsed(edge: RailEdge, storage: SizeStorage | null = deviceStorage()): LastUsed {
  if (!storage) return [];
  let raw: string | null = null;
  try {
    raw = storage.getItem(lastUsedKey(edge));
  } catch {
    return [];
  }
  if (!raw) return [];
  try {
    const list: unknown = JSON.parse(raw);
    return Array.isArray(list) ? list.slice(0, 2).map((one) => (typeof one === 'string' && one ? one : null)) : [];
  } catch {
    return [];
  }
}

export function writeLastUsed(edge: RailEdge, last: LastUsed, storage: SizeStorage | null = deviceStorage()): void {
  if (!storage) return;
  try {
    storage.setItem(lastUsedKey(edge), JSON.stringify(last.slice(0, 2)));
  } catch {
  }
}
