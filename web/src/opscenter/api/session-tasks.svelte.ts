import { authFetch } from './auth.svelte';
import { resource, type Resource } from './poll.svelte';

export const SESSION_TASKS_POLL_MS = 10000;
export const ALL_TASKS_KEY = '*';

export type TaskStatus = 'pending' | 'in_progress' | 'completed';

export interface TaskItem {
  id: string;
  subject: string;
  active_form: string | null;
  status: TaskStatus;
}

export interface SessionTasks {
  state: 'ok' | 'empty' | 'unknown' | 'unsupported' | 'remote';
  session_id: string | null;
  label: string | null;
  tasks: TaskItem[];
  counts: { pending: number; in_progress: number; completed: number };
}

export interface AllSessionTasks {
  sessions: SessionTasks[];
}

const cache = new Map<string, { resource: Resource<unknown>; refs: number }>();

function hold<T>(key: string, path: string, topicKey: string): Resource<T> {
  let entry = cache.get(key);
  if (!entry) {
    entry = {
      resource: resource<T>(() => authFetch<T>(path), {
        intervalMs: SESSION_TASKS_POLL_MS,
        topics: [`session_tasks:${topicKey}`],
        name: `session-tasks:${key}`,
      }),
      refs: 0,
    };
    cache.set(key, entry);
  }
  entry.refs += 1;
  return entry.resource as Resource<T>;
}

function drop(key: string): void {
  const entry = cache.get(key);
  if (!entry) return;
  entry.refs -= 1;
  if (entry.refs <= 0) {
    entry.resource.stop();
    cache.delete(key);
  }
}

export function sessionTasks(sessionId: string): Resource<SessionTasks> {
  return hold<SessionTasks>(`s:${sessionId}`, `/sessions/${encodeURIComponent(sessionId)}/tasks`, sessionId);
}

export function releaseSessionTasks(sessionId: string): void {
  drop(`s:${sessionId}`);
}

export function allSessionTasks(): Resource<AllSessionTasks> {
  return hold<AllSessionTasks>('all', '/session-tasks', ALL_TASKS_KEY);
}

export function releaseAllSessionTasks(): void {
  drop('all');
}
