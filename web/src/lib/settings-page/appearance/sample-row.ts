import type { RowHost } from '../../sidebar-shell/row-host';
import { rowHost } from '../../sidebar-shell/row-host';

export const SAMPLE_ROW_NAME = 'carnivore-web';

export function sampleRow(now: number = Date.now()): Record<string, unknown> {
    return {
        name: SAMPLE_ROW_NAME, label: SAMPLE_ROW_NAME, created_by_cloude: true, status: 'working', unread: false,
        agent_family: 'claude', session_id: 'ses_sample', session_uuid: 'sample-agent-row', kind: 'agent',
        running_model: 'claude-opus-5', running_model_effort: 'high', running_model_tier: 5,
        running_context_used_pct: 44, subagents_running: 2, subagents_total: 3, background_open: 3,
        timers_live: 2, timers_next_fire_at: new Date(now + 4 * 60 * 1000).toISOString(),
        workflow_active: false, last_work_at: new Date(now - 12 * 60 * 1000).toISOString(),
        host_key: 'local', host_label: 'this machine', host_state: 'up', is_pinned: false,
    };
}

export function previewHost(base: RowHost = rowHost()): RowHost {
    return { ...base, autoSleep: { isKeptAwake: () => true } };
}
