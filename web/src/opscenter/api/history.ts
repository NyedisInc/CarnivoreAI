/* there is nothing */

import { isDemo } from './demo';

export const CAPACITY = 120;

const STORAGE_KEY = 'cloudecode.opscenter.history.v1';

export const KEYS = {
  running: 'stat.running',
  sessions24h: 'stat.sessions-24h',
  projects: 'stat.open-projects',
  ledger: 'stat.ledger-usage',
  alive: 'stat.sessions-alive',
  skills: 'stat.skills-installed',
  subagents: 'stat.subagents-running',
} as const;

const DEMO_SERIES: Readonly<Record<string, readonly number[]>> = {
  [KEYS.running]: [2, 3, 7, 12, 8, 11],
  [KEYS.sessions24h]: [9, 13, 16, 14, 23, 31],
  [KEYS.projects]: [5, 5, 8, 13, 10, 21],
  [KEYS.ledger]: [15, 15, 27, 45, 42, 94],
  [KEYS.alive]: [13, 17, 20, 26, 33],
  [KEYS.skills]: [2, 3, 3, 4, 4, 5],
  [KEYS.subagents]: [0, 2, 1, 4, 3, 5],
};

type Series = number[];

type Store = Record<string, Series>;

function store(): Storage | null {
  try {
    const held = globalThis.sessionStorage;
    if (!held) return null;
    held.getItem(STORAGE_KEY);
    return held;
  } catch {
    return null;
  }
}

function load(): Store {
  const held = store();
  if (!held) return {};
  try {
    const raw = held.getItem(STORAGE_KEY);
    if (!raw) return {};
    const parsed: unknown = JSON.parse(raw);
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return {};
    const out: Store = {};
    for (const [key, value] of Object.entries(parsed as Record<string, unknown>)) {
      if (!Array.isArray(value)) continue;
      const numbers = value.filter((entry): entry is number => typeof entry === 'number' && Number.isFinite(entry));
      out[key] = numbers.slice(-CAPACITY);
    }
    return out;
  } catch {
    return {};
  }
}

function save(value: Store): void {
  const held = store();
  if (!held) return;
  try {
    held.setItem(STORAGE_KEY, JSON.stringify(value));
  } catch {
  }
}

let cache: Store | null = null;

const sampled = new Map<string, number>();

function ensure(): Store {
  if (cache !== null) return cache;
  if (isDemo()) {
    const seeded: Store = {};
    for (const [key, values] of Object.entries(DEMO_SERIES)) seeded[key] = values.slice();
    cache = seeded;
    return cache;
  }
  cache = load();
  return cache;
}

export const history = {
  record(key: string, value: number): void {
    if (!Number.isFinite(value)) return;
    const held = ensure();
    const series = held[key] ?? [];
    series.push(value);
    held[key] = series.slice(-CAPACITY);
    if (!isDemo()) save(held);
  },

  sample(key: string, value: number | null, stamp: number | null): void {
    if (isDemo()) return;
    if (stamp === null || value === null || !Number.isFinite(value)) return;
    if (sampled.get(key) === stamp) return;
    sampled.set(key, stamp);
    this.record(key, value);
  },

  series(key: string): number[] {
    return (ensure()[key] ?? []).slice();
  },

  clear(): void {
    cache = {};
    sampled.clear();
    save(cache);
  },
};
