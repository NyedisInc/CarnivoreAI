/* scheduled tasks */
import { authFetch } from './auth.svelte';
import { resource, type Resource } from './poll.svelte';

export const SCHEDULED_TASKS_POLL_MS = 60000;

export interface ScheduledTaskRow {
  id: string;
  name: string;
  description: string | null;
  file_state: 'ok' | 'missing' | 'too_large' | 'unreadable' | 'no_frontmatter';
  schedule: string | null;
  schedule_source: 'frontmatter' | 'not_recorded';
  next_run_at: string | null;
  last_run_at: string | null;
  runs_recorded: number;
  updated_at: string | null;
  host_key?: string | null;
  host_label?: string | null;
}

export interface ScheduledTasksList {
  state: 'ok' | 'absent' | 'unreadable';
  tasks: ScheduledTaskRow[];
  total: number;
  truncated: boolean;
  runs_truncated: boolean;
  detail: string;
  as_of: string | null;
}

function demoTasks(): ScheduledTasksList {
  return {
    state: 'ok',
    tasks: [
      {
        id: 'nightly-check', name: 'nightly-check', description: 'check the placeholder fleet',
        file_state: 'ok', schedule: null, schedule_source: 'not_recorded', next_run_at: null,
        last_run_at: '2026-09-26T21:00:05Z', runs_recorded: 12, updated_at: '2026-09-01T12:00:00Z',
      },
      {
        id: 'weekly-report', name: 'weekly-report', description: 'write the placeholder report',
        file_state: 'ok', schedule: null, schedule_source: 'not_recorded', next_run_at: null,
        last_run_at: null, runs_recorded: 0, updated_at: '2026-09-01T12:00:00Z',
      },
    ],
    total: 2, truncated: false, runs_truncated: false, detail: '', as_of: null,
  };
}

let current = $state.raw<Resource<ScheduledTasksList> | null>(null);
let refs = 0;

export function acquireScheduledTasks(): Resource<ScheduledTasksList> {
  if (current === null) {
    current = resource<ScheduledTasksList>(() => authFetch<ScheduledTasksList>('/scheduled-tasks'), {
      intervalMs: SCHEDULED_TASKS_POLL_MS,
      name: 'scheduled-tasks',
      demo: demoTasks,
    });
  }
  refs += 1;
  return current;
}

export function releaseScheduledTasks(): void {
  if (current === null) return;
  refs -= 1;
  if (refs <= 0) {
    current.stop();
    current = null;
    refs = 0;
  }
}

export function scheduledTasks(): Resource<ScheduledTasksList> | null {
  return current;
}
