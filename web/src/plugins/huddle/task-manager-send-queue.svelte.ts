import { authFetch, familyOf, resourcePush } from '../sdk';
import { AGGREGATE, serverKey } from './huddle-model';
import { applyFlushHold, holdFlushed } from './task-manager-flush-hold';
import { huddle } from './huddle.svelte';

export const SEND_QUEUE_FAMILY = 'cplug.huddle.sendq';
export const REREAD_AFTER_DUE_MS = 1500;

export interface QueuedList {
  count: number;
  first_at: number;
  last_at: number;
  due_at: number;
}

export interface SendQueueState {
  now: number;
  quiet_s: number;
  cap_s: number;
  count: number;
  first_at: number | null;
  reset_at: number | null;
  due_at: number | null;
  lists: Record<string, QueuedList>;
}

export interface QueueSummary {
  count: number;
  resetAt: number;
  dueAt: number;
}

export interface FillProgress {
  fraction: number;
  durationS: number;
  elapsedS: number;
}

export const sendQueue = $state<{ state: SendQueueState | null; skewMs: number }>({ state: null, skewMs: 0 });

export function queueSummary(state: SendQueueState | null, selected: string): QueueSummary | null {
  if (!state) return null;
  const rows = Object.entries(state.lists ?? {}).filter(([key]) => selected === AGGREGATE || key === serverKey(selected)).map(([, row]) => row);
  if (!rows.length) return null;
  return {
    count: rows.reduce((sum, row) => sum + row.count, 0),
    resetAt: Math.max(...rows.map((row) => row.last_at)),
    dueAt: Math.min(...rows.map((row) => row.due_at)),
  };
}

export function queuedKeys(state: SendQueueState | null, selected: string): string[] {
  return Object.keys(state?.lists ?? {}).filter((key) => selected === AGGREGATE || key === serverKey(selected));
}

export function fillProgress(summary: QueueSummary, nowMs: number, skewMs: number): FillProgress {
  const durationS = Math.max(summary.dueAt - summary.resetAt, 0);
  const elapsedS = Math.min(Math.max((nowMs + skewMs) / 1000 - summary.resetAt, 0), durationS);
  return { fraction: durationS > 0 ? elapsedS / durationS : 1, durationS, elapsedS };
}

let started = false;
let reread: ReturnType<typeof setTimeout> | null = null;

export function applyQueue(next: SendQueueState | null | undefined): void {
  if (!next || typeof next.count !== 'number') return;
  const sent = Object.keys(sendQueue.state?.lists ?? {}).filter((key) => !(key in (next.lists ?? {})));
  sendQueue.state = next;
  if (sent.length) {
    holdFlushed(sent);
    huddle.lists = applyFlushHold(huddle.lists);
  }
  sendQueue.skewMs = typeof next.now === 'number' ? next.now * 1000 - Date.now() : 0;
  if (reread) clearTimeout(reread);
  reread = null;
  if (next.due_at !== null && next.due_at !== undefined) {
    const wait = next.due_at * 1000 - (Date.now() + sendQueue.skewMs) + REREAD_AFTER_DUE_MS;
    reread = setTimeout(() => void refreshSendQueue(), Math.max(wait, REREAD_AFTER_DUE_MS));
  }
}

export async function refreshSendQueue(): Promise<void> {
  try {
    applyQueue(await authFetch<SendQueueState | null>('/cplugs/huddle/send-queue'));
  } catch (error) {
    console.warn('huddle: could not read the send queue', error);
  }
}

export function startSendQueue(): void {
  if (started) return;
  started = true;
  resourcePush().onChange((topics) => {
    if (topics.some((topic) => familyOf(topic) === SEND_QUEUE_FAMILY)) void refreshSendQueue();
  });
  void refreshSendQueue();
}

export function resetSendQueue(): void {
  sendQueue.state = null;
  sendQueue.skewMs = 0;
  if (reread) clearTimeout(reread);
  reread = null;
}
