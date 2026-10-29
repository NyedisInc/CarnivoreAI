import type { HistoryGroup, HistorySession } from './history-api';

export function session(patch: Partial<HistorySession>): HistorySession {
    return {
        session_uuid: 'u1', row_id: 1, title: 'api', label: 'api', tmux_name: 'cloude_api', host_key: 'local',
        state: 'closed', lifecycle: 'stopped', lifecycle_source: 'tmux_missing', archived_at: null,
        agent_type: 'claude max', agent_family: 'claude', claude_session_uuid: null, has_transcript: false,
        created_at: null, last_seen_running_at: null, last_work_at: null, last_activity_at: '2026-09-27T10:00:00Z',
        working_dir: '/x/alpha', origin: 'created', kind: null, fork_kind: null, live_session_id: null,
        ...patch,
    };
}

export function group(patch: Partial<HistoryGroup> & { name?: string }): HistoryGroup {
    const { name = 'alpha', ...rest } = patch;
    return {
        key: name,
        project: { id: 1, name, root: `/x/${name}`, description: null, archived_at: null, last_opened_at: null, created_at: null, default_theme: null },
        session_total: 0, counts: {}, automated_counts: {}, activity_days: [], last_activity_at: '2026-09-27T10:00:00Z', sessions: [],
        ...rest,
    };
}
