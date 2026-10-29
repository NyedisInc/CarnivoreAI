import type { QueryResult } from './types';

export const SNAPSHOT_VERSION = 1;
const KEY = 'carnivore.analytics.snapshot';
export const SNAPSHOT_MAX_CHARS = 300_000;
const WRITE_DELAY_MS = 400;

export interface CardSnapshot {
  shape: string;
  asOf: string;
  results: (QueryResult | null)[];
  headline: QueryResult | null;
  context: QueryResult[];
}

interface Stored { v: number; cards: Record<string, CardSnapshot & { saved: number }> }

let memory: Stored | null = null;
let timer: ReturnType<typeof setTimeout> | null = null;

function store(): Stored {
  if (memory) return memory;
  memory = { v: SNAPSHOT_VERSION, cards: {} };
  try {
    const raw = globalThis.localStorage?.getItem(KEY);
    const parsed = raw ? JSON.parse(raw) as Stored : null;
    if (parsed && parsed.v === SNAPSHOT_VERSION && parsed.cards && typeof parsed.cards === 'object') memory = parsed;
  } catch {
  }
  return memory;
}

export function readSnapshot(id: string, shape: string): CardSnapshot | null {
  const card = store().cards[id];
  return card && card.shape === shape && Array.isArray(card.results) ? card : null;
}

function persist(): void {
  timer = null;
  const current = store();
  try {
    let text = JSON.stringify(current);
    while (text.length > SNAPSHOT_MAX_CHARS) {
      const oldest = Object.entries(current.cards).sort((a, b) => a[1].saved - b[1].saved)[0];
      if (!oldest) return;
      delete current.cards[oldest[0]];
      text = JSON.stringify(current);
    }
    globalThis.localStorage?.setItem(KEY, text);
  } catch {
  }
}

export function writeSnapshot(id: string, snapshot: CardSnapshot): void {
  store().cards[id] = { ...snapshot, saved: Date.now() };
  if (timer === null) timer = setTimeout(persist, WRITE_DELAY_MS);
}

export function resetSnapshotMemory(): void {
  memory = null;
  if (timer !== null) { clearTimeout(timer); timer = null; }
}
