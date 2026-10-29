import { authFetch } from './auth.svelte';
import { resource, type Resource } from './poll.svelte';
import { TASK_MANAGER_TOPICS } from '../../lib/task-manager-schedules/task-manager-scheduled';

export const SENT_POLL_MS = 15000;
export const SENT_LIMIT = 40;
export const SENT_TOPICS: readonly string[] = [...TASK_MANAGER_TOPICS, 'cplug.huddle.sendq', 'cplug.huddle.held', 'cplug.huddle.told'];
export const SENT_ROUTE = '/cplugs/huddle/sent';

export interface SentTell {
  state: string;
  label: string | null;
  at: number | null;
  due_at: number | null;
  reason: string | null;
}

export interface SentSend {
  key: string;
  kind: 'reply' | 'answer' | 'round' | 'add';
  at: number;
  text: string;
  list: string;
  list_name: string | null;
  session?: string | null;
  item: { id: number; title: string } | null;
  board: { slug: string; round: string } | null;
  tell: SentTell;
}

export interface Sent {
  now: number;
  sends: SentSend[];
}

export function readSent(): Promise<Sent> {
  return authFetch<Sent>(`${SENT_ROUTE}?limit=${SENT_LIMIT}`);
}

let current: Resource<Sent> | null = null;
let refs = 0;

export function acquireSent(): Resource<Sent> {
  if (current === null) {
    current = resource<Sent>(readSent, { intervalMs: SENT_POLL_MS, topics: SENT_TOPICS, name: 'sent', demo: () => ({ now: 0, sends: [] }) });
  }
  refs += 1;
  return current;
}

export function releaseSent(): void {
  if (current === null) return;
  refs -= 1;
  if (refs <= 0) {
    current.stop();
    current = null;
    refs = 0;
  }
}
