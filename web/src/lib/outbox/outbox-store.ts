import { isEntry, type OutboxEntry } from './outbox-model';

export const OUTBOX_KEY = 'carnivore.outbox.v1';
export const MAX_STORED_ENTRIES = 200;
export const MAX_STORED_CHARS = 1_500_000;

let entries: OutboxEntry[] = [];
let stored = true;
let loaded = false;
const listeners = new Set<() => void>();

function emit(): void {
  for (const fn of [...listeners]) {
    try {
      fn();
    } catch (error) {
      console.warn('outbox: a subscriber threw', error);
    }
  }
}

function readStorage(): OutboxEntry[] | null {
  try {
    const raw = globalThis.localStorage?.getItem(OUTBOX_KEY);
    if (raw === null || raw === undefined) return [];
    const parsed: unknown = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed.filter(isEntry) : [];
  } catch (error) {
    console.warn('outbox: could not read the stored copy', error);
    return null;
  }
}

function persist(): void {
  let fits = entries;
  if (fits.length > MAX_STORED_ENTRIES) fits = fits.slice(fits.length - MAX_STORED_ENTRIES);
  let json = JSON.stringify(fits);
  while (json.length > MAX_STORED_CHARS && fits.length > 0) {
    fits = fits.slice(1);
    json = JSON.stringify(fits);
  }
  try {
    globalThis.localStorage.setItem(OUTBOX_KEY, json);
    stored = fits.length === entries.length;
  } catch (error) {
    stored = false;
    console.warn('outbox: could not keep a copy in this browser', error);
  }
}

function load(): void {
  if (loaded) return;
  loaded = true;
  const found = readStorage();
  if (found === null) stored = false;
  else entries = found;
}

export function listEntries(): OutboxEntry[] {
  load();
  return [...entries];
}

export function isStored(): boolean {
  load();
  return stored;
}

export function putEntry(entry: OutboxEntry): void {
  load();
  const at = entries.findIndex((e) => e.id === entry.id);
  if (at >= 0) entries[at] = entry;
  else entries = [entry, ...entries];
  persist();
  emit();
}

export function removeEntry(id: string): void {
  load();
  entries = entries.filter((e) => e.id !== id);
  persist();
  emit();
}

export function findEntry(id: string): OutboxEntry | undefined {
  load();
  return entries.find((e) => e.id === id);
}

export function subscribe(fn: () => void): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

function onStorage(event: StorageEvent): void {
  if (event.key !== null && event.key !== OUTBOX_KEY) return;
  const found = readStorage();
  if (found === null) return;
  load();
  const unsaved = stored ? [] : entries.filter((e) => !found.some((f) => f.id === e.id));
  entries = [...unsaved, ...found];
  emit();
}

export function watchStorage(): void {
  globalThis.addEventListener?.('storage', onStorage);
}

export function resetStore(): void {
  entries = [];
  stored = true;
  loaded = false;
  emit();
}
