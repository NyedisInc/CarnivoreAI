import { bridge } from '../zone-shell/preference-field';
import { appendRead, mergeRead } from './logic/feed';

export const SEEN_FIELD = 'automation_runs_seen_at';
export const READ_FIELD = 'automation_runs_read';
const DEBOUNCE_MS = 1000;
const ID_RE = /^[A-Za-z0-9_-]{1,80}$/;

export const unread = $state({ seenAt: null as string | null, read: [] as string[] });

let timer: ReturnType<typeof setTimeout> | null = null;
let dirty = false;
let markGen = 0;
const RETRY_MS = 5000;

function cleanSeen(value: unknown): string | null {
  return typeof value === 'string' && Number.isFinite(Date.parse(value)) ? value : null;
}

function cleanRead(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((id): id is string => typeof id === 'string' && ID_RE.test(id)).slice(-500) : [];
}

function adopt(): void {
  const b = bridge();
  if (!b || dirty) return;
  unread.seenAt = cleanSeen(b.read(SEEN_FIELD, () => null));
  unread.read = cleanRead(b.read(READ_FIELD, () => null));
}

export function startReadState(): () => void {
  adopt();
  const b = bridge();
  if (!b) return () => {};
  const stops = [b.follow(SEEN_FIELD, () => adopt()), b.follow(READ_FIELD, () => adopt())];
  return () => stops.forEach((stop) => stop());
}

function entries(): { field: string; value: unknown; localWriter: () => void }[] {
  const out: { field: string; value: unknown; localWriter: () => void }[] = [
    { field: READ_FIELD, value: unread.read, localWriter: () => {} },
  ];
  if (unread.seenAt !== null) out.push({ field: SEEN_FIELD, value: unread.seenAt, localWriter: () => {} });
  return out;
}

async function writeOnce(b: NonNullable<ReturnType<typeof bridge>>): Promise<void> {
  const first = (await b.writeMany(entries())) as { status?: string } | undefined;
  if (first?.status !== 'stale_revision') return;
  const prefs = (globalThis as { Preferences?: { committedValue?(name: string): unknown } }).Preferences;
  const merged = mergeRead(
    { seenAt: cleanSeen(prefs?.committedValue?.(SEEN_FIELD)), read: cleanRead(prefs?.committedValue?.(READ_FIELD)) },
    { seenAt: unread.seenAt, read: unread.read },
  );
  unread.seenAt = merged.seenAt;
  unread.read = merged.read;
  const replay = (await b.writeMany(entries())) as { status?: string } | undefined;
  if (replay?.status === 'stale_revision') throw new Error('stale_revision after replay');
}

export async function flushReadState(): Promise<void> {
  if (timer) clearTimeout(timer);
  timer = null;
  const b = bridge();
  if (!b || !dirty) return;
  const gen = markGen;
  try {
    await writeOnce(b);
  } catch (error) {
    console.warn('[automations] could not write the unread state; retrying', error);
    timer = setTimeout(() => void flushReadState(), RETRY_MS);
    return;
  }
  if (gen === markGen) dirty = false;
  else schedule();
}

function schedule(): void {
  dirty = true;
  markGen += 1;
  if (timer) clearTimeout(timer);
  timer = setTimeout(() => void flushReadState(), DEBOUNCE_MS);
}

export function markRead(ids: readonly string[]): void {
  const fresh = ids.filter((id) => ID_RE.test(id) && !unread.read.includes(id));
  if (!fresh.length) return;
  unread.read = appendRead(unread.read, fresh);
  schedule();
}

export function markAllRead(now: Date = new Date()): void {
  unread.seenAt = now.toISOString();
  unread.read = [];
  schedule();
}
