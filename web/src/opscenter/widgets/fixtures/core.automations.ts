import { epochAgo, HOUR, MIN } from './clock';
import { sessionList, TERMINAL_ROW_ID } from './made-up';
import type { WidgetFixtures } from './types';

const SESSION_UUID = '0edffbc5-38a8-4edc-8c9a-e9bab14a8b5d';
const APP_ACTOR = { kind: 'app' };

function run(automationId: string, status: 'succeeded' | 'failed', endedAgo: number, extra: Record<string, unknown> = {}): unknown {
  return {
    run_id: `${automationId}-run`, automation_id: automationId, trigger: 'schedule', slot_at: epochAgo(endedAgo + 30), status, reason: null,
    skip_count: null, first_slot_at: null, last_slot_at: null, started_at: epochAgo(endedAgo + 30), ended_at: epochAgo(endedAgo), cost_usd: 0.42,
    error: status === 'failed' ? 'the session was busy' : null, has_report: false, ...extra,
  };
}

function automation(id: string, name: string, cron: string, enabled: boolean, target: Record<string, unknown>, nextInS: number | null, last: unknown): unknown {
  return {
    automation_id: id, name, enabled, trigger: { cron, timezone: 'UTC' }, target, delivery: { notify: true, notify_on: 'failure' },
    next_fire_at: nextInS === null ? null : epochAgo(-nextInS), revision: 1, created_at: epochAgo(9 * 24 * HOUR), updated_at: epochAgo(2 * 24 * HOUR),
    created_by: 'owner', created_actor: APP_ACTOR, updated_by: 'owner', updated_actor: APP_ACTOR, retry_due_at: null, last_run: last,
    description: '', project_id: null, misfire: 'skip', retry_max: 0, retry_backoff_s: 0, max_runtime_s: null,
  };
}

const AUTOMATIONS = [
  automation('a1', 'nightly invoice check', '0 2 * * *', true, { kind: 'session_message', session_uuid: SESSION_UUID, text: 'check the failed invoices' }, 5 * HOUR, run('a1', 'failed', 20 * HOUR)),
  automation('a2', 'weekly retry policy review', '0 9 * * 1', false, { kind: 'session_message', session_uuid: SESSION_UUID, text: 'review the retry policy' }, null, null),
  automation('a3', 'sleep idle sessions', '*/30 * * * *', true, { kind: 'system_action', recipe: 'sleep_idle' }, 12 * MIN, run('a3', 'succeeded', 18 * MIN)),
  automation('a4', 'save catch-up', '15 * * * *', true, { kind: 'system_action', recipe: 'save_catch_up' }, 41 * MIN, run('a4', 'succeeded', 19 * MIN)),
  automation('a5', 'quarterly reconciliation report for the billing ledger and the payout provider', '0 6 1 */3 *', true, { kind: 'agent_run', project: 'billing-api' }, 20 * 24 * HOUR, null),
];

export const automationsFixtures: WidgetFixtures = {
  data: {
    'GET /sessions/list': sessionList(),
    'GET /automations': { automations: AUTOMATIONS, timers_status: { state: 'ok', total: AUTOMATIONS.length, enabled: 4 } },
    'GET /sessions/records': [{ id: TERMINAL_ROW_ID, session_uuid: SESSION_UUID, tmux_name: 'cloude_billing-api', lifecycle: 'running' }],
  },
  empty: {
    'GET /sessions/list': sessionList(),
    'GET /automations': { automations: [], timers_status: { state: 'none', total: 0, enabled: 0 } },
    'GET /sessions/records': [{ id: TERMINAL_ROW_ID, session_uuid: SESSION_UUID, tmux_name: 'cloude_billing-api', lifecycle: 'running' }],
  },
};
