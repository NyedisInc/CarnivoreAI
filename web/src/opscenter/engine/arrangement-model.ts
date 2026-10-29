import type { TabGroups } from './tabs';
import type { Layout } from './types';
import { MAX_SESSION_LAYOUTS } from './session-layouts';
import { readStoredGrid } from './v7/adapt';

export const TERMINAL_LAYOUTS_FIELD = 'terminal_layouts';

export interface ArrangementEntry {
  layout: Layout | null;
  groups: TabGroups;
}

export interface Arrangement {
  v: 1;
  sessions: Record<string, ArrangementEntry>;
}

export function emptyArrangement(): Arrangement {
  return { v: 1, sessions: {} };
}

function isObject(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value);
}

function gridOf(raw: unknown): Layout | null {
  if (!isObject(raw)) return null;
  const stored = readStoredGrid(raw, 'terminal');
  if (stored.kind === 'v7') return stored.grid;
  if (stored.kind === 'v7-refused') return null;
  return raw as unknown as Layout;
}

export function parseArrangement(value: unknown): Arrangement | null {
  if (value === undefined || value === null) return null;
  const out = emptyArrangement();
  if (!isObject(value) || !isObject(value.sessions)) return out;
  for (const [key, raw] of Object.entries(value.sessions)) {
    if (!key || !isObject(raw)) continue;
    const groups: TabGroups = {};
    if (isObject(raw.groups)) {
      for (const [slot, group] of Object.entries(raw.groups)) {
        const tabs = isObject(group) && Array.isArray(group.tabs) ? group.tabs : [];
        groups[slot] = { tabs: tabs.filter((tab): tab is string => typeof tab === 'string') };
      }
    }
    out.sessions[key] = { layout: gridOf(raw.layout), groups };
  }
  return out;
}

export function upsertEntry(map: Arrangement, key: string, entry: ArrangementEntry): Arrangement {
  const sessions: Record<string, ArrangementEntry> = {};
  const others = Object.keys(map.sessions).filter((name) => name !== key);
  for (const name of others.slice(Math.max(0, others.length - (MAX_SESSION_LAYOUTS - 1)))) {
    sessions[name] = map.sessions[name]!;
  }
  sessions[key] = entry;
  return { v: 1, sessions };
}

export function sameEntry(a: ArrangementEntry | undefined, b: ArrangementEntry | undefined): boolean {
  if (!a || !b) return a === b;
  return stable(a) === stable(b);
}

function stable(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(stable).join(',')}]`;
  if (isObject(value)) {
    return `{${Object.keys(value)
      .sort()
      .filter((key) => value[key] !== undefined)
      .map((key) => `${JSON.stringify(key)}:${stable(value[key])}`)
      .join(',')}}`;
  }
  return JSON.stringify(value) ?? 'null';
}
