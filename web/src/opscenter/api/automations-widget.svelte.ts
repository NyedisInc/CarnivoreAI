import { authFetch } from './auth.svelte';
import { listingRows, resource, type Resource } from './poll.svelte';
import type { Automation } from '../../lib/automations/api';

export const AUTOMATIONS_POLL_MS = 15000;
export const AUTOMATIONS_WIDGET_TOPICS: readonly string[] = ['automations', 'automation_runs'];

export interface TimersStatus {
  state: 'none' | 'ok' | 'warning' | 'error' | 'disabled';
  total: number;
  enabled: number;
}

export interface AutomationsAnswer {
  automations: Automation[];
  timers_status?: TimersStatus;
}

let current: Resource<AutomationsAnswer> | null = null;
let refs = 0;

export function automationsList(): Resource<AutomationsAnswer> {
  if (!current) {
    current = resource<AutomationsAnswer>(() => authFetch<AutomationsAnswer>('/automations'), {
      intervalMs: AUTOMATIONS_POLL_MS,
      topics: [...AUTOMATIONS_WIDGET_TOPICS],
      name: 'automations-widget',
    });
  }
  refs += 1;
  return current;
}

export function releaseAutomationsList(): void {
  if (!current) return;
  refs -= 1;
  if (refs <= 0) {
    current.stop();
    current = null;
    refs = 0;
  }
}

export async function sessionUuidOfRow(rowId: number): Promise<string | null> {
  const rows = await listingRows<{ session_row_id?: number | null; session_uuid?: string | null }>('list', '/sessions/list');
  return rows.find((r) => r.session_row_id === rowId)?.session_uuid ?? null;
}
