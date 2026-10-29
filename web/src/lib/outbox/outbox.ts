import { authFetch } from '../../opscenter/api/auth.svelte';
import { newClientId } from './client-id';
import {
  retryAge, WAIT_FOR_TRIGGER, type NewOutboxEntry, type OutboxEntry, type OutboxError, type OutboxResult,
} from './outbox-model';
import { findEntry, isStored, listEntries, putEntry, removeEntry, subscribe, watchStorage } from './outbox-store';

export const BACKOFF_MS: readonly number[] = [2000, 5000, 15000, 30000, 60000];
export const LONG_WAIT_MS = 120000;
export const LEASE_MS = 20000;
const ANSWERED_CODE = 'task_manager_answered';
const RETRYABLE_CODES: readonly string[] = ['cplug_disabled'];

const TAB = newClientId();
let timer: ReturnType<typeof setTimeout> | null = null;
let started = false;

function codeOf(error: unknown): string | null {
  const e = error as { code?: unknown; payload?: { detail?: { code?: unknown }; code?: unknown } | null } | null;
  const found = e?.payload?.detail?.code ?? e?.payload?.code ?? e?.code;
  return typeof found === 'string' ? found : null;
}

export function classify(error: unknown, attempts: number): { retry: boolean; wait: number; record: OutboxError } {
  const e = error as { status?: unknown; message?: unknown } | null;
  const status = typeof e?.status === 'number' && e.status > 0 ? e.status : null;
  const code = codeOf(error);
  const message = code === ANSWERED_CODE ? ANSWERED_CODE : typeof e?.message === 'string' && e.message ? e.message : 'the server did not answer';
  const record: OutboxError = { status, code, message };
  const backoff = BACKOFF_MS[attempts - 1] ?? LONG_WAIT_MS;
  if (status === null) return { retry: true, wait: backoff, record };
  if (status === 401) return { retry: true, wait: WAIT_FOR_TRIGGER, record };
  const retryable = status === 408 || status === 425 || status === 429 || status >= 500
    || (code !== null && RETRYABLE_CODES.includes(code));
  return { retry: retryable, wait: retryable ? backoff : WAIT_FOR_TRIGGER, record };
}

function leasedByOther(entry: OutboxEntry, nowMs: number): boolean {
  return !!entry.lease && entry.lease.tab !== TAB && entry.lease.until > nowMs;
}

async function attempt(id: string, live: boolean): Promise<OutboxResult> {
  const found = findEntry(id);
  const now = Date.now();
  if (!found) return { ok: false, kept: true, error: { status: null, code: null, message: 'gone' } };
  if (leasedByOther(found, now)) return { ok: false, kept: true, error: { status: null, code: null, message: 'another tab is sending it' } };
  const tries = found.attempts + 1;
  const sending: OutboxEntry = { ...found, attempts: tries, state: 'sending', lease: { tab: TAB, until: now + LEASE_MS } };
  putEntry(sending);
  const body = tries >= 2 && sending.ageField ? { ...sending.request.body, [sending.ageField]: retryAge(sending, now) } : sending.request.body;
  try {
    const answer = await authFetch<unknown>(sending.request.path, { method: sending.request.method, body: JSON.stringify(body) });
    removeEntry(id);
    if (!live && sending.after) await runAfter(sending.after);
    schedule();
    return { ok: true, answer };
  } catch (error) {
    const sort = classify(error, tries);
    const next: OutboxEntry = {
      ...sending, lease: null, error: sort.record,
      state: sort.retry ? 'pending' : 'failed', next_at: sort.retry ? (sort.wait === WAIT_FOR_TRIGGER ? WAIT_FOR_TRIGGER : Date.now() + sort.wait) : WAIT_FOR_TRIGGER,
    };
    putEntry(next);
    schedule();
    return sort.retry ? { ok: false, kept: true, error: sort.record } : { ok: false, kept: false, error: sort.record, cause: error };
  }
}

async function runAfter(after: NonNullable<OutboxEntry['after']>): Promise<void> {
  try {
    await authFetch<unknown>(after.path, { method: 'POST', body: JSON.stringify(after.body) });
  } catch (error) {
    console.warn('outbox: the follow-up after a replayed send failed', error);
  }
}

/* did not answer */
export async function send(spec: NewOutboxEntry): Promise<OutboxResult> {
  startOutbox();
  const kept = findEntry(spec.id);
  if (!kept) {
    putEntry({ ...spec, created_at: Date.now(), attempts: 0, next_at: WAIT_FOR_TRIGGER, state: 'pending', error: null, lease: null });
  } else if (!leasedByOther(kept, Date.now())) {
    putEntry({ ...kept, kind: spec.kind, request: spec.request, ageField: spec.ageField, after: spec.after, label: spec.label, state: 'pending', next_at: WAIT_FOR_TRIGGER, lease: null });
  }
  return attempt(spec.id, true);
}

function isStranded(entry: OutboxEntry, nowMs: number): boolean {
  return entry.state === 'sending' && (!entry.lease || entry.lease.until <= nowMs);
}

export function keptNoticeKey(): string {
  return isStored() ? 'cplug.huddle.outbox.kept' : 'cplug.huddle.outbox.keptMemory';
}

async function flush(all: boolean): Promise<void> {
  const now = Date.now();
  const due = listEntries().filter((e) => isStranded(e, now) || (e.state === 'pending' && (all || e.next_at <= now)));
  for (const e of due.reverse()) await attempt(e.id, false);
}

function schedule(): void {
  if (timer !== null) clearTimeout(timer);
  timer = null;
  const times = listEntries().flatMap((e) => {
    if (e.state === 'pending' && e.next_at !== WAIT_FOR_TRIGGER) return [e.next_at];
    return e.state === 'sending' ? [e.lease ? e.lease.until : 0] : [];
  });
  if (!times.length) return;
  timer = setTimeout(() => { timer = null; void flush(false); }, Math.max(0, Math.min(...times) - Date.now()));
}

export function retryNow(id: string): Promise<OutboxResult> {
  return attempt(id, false);
}

export function discard(id: string): void {
  removeEntry(id);
  schedule();
}

export function entries(): OutboxEntry[] {
  return listEntries();
}

export function startOutbox(): void {
  if (started) return;
  started = true;
  watchStorage();
  subscribe(schedule);
  const again = (): void => { void flush(true); };
  globalThis.addEventListener?.('online', again);
  globalThis.document?.addEventListener?.('visibilitychange', () => { if (globalThis.document.visibilityState === 'visible') again(); });
  const events = (globalThis as { AppEvents?: { subscribe?: (fn: (frame: { type?: string }) => void) => unknown } }).AppEvents;
  events?.subscribe?.((frame) => { if (frame?.type === 'events.hello') again(); });
  schedule();
  void flush(false);
}

export function stopOutbox(): void {
  if (timer !== null) clearTimeout(timer);
  timer = null;
  started = false;
}
