import { contextFromRow, type RowMenuCtx } from '../item-menu/row-context';
import type { SessionListItem } from '../sessions/types';
import type { HistorySession } from './history-api';

const OWNED_ORIGINS = ['created', 'adopted'];

export function sessionMenuContext(session: HistorySession, live: SessionListItem | undefined, unread: boolean): RowMenuCtx | null {
    if (session.state !== 'running' && session.state !== 'asleep') return null;
    if (session.host_key && session.host_key !== 'local') return null;
    const asleep = session.state === 'asleep';
    const wire = (live ?? {}) as Record<string, unknown>;
    return contextFromRow(
        {
            name: session.tmux_name ?? '',
            label: session.title,
            session_id: session.live_session_id,
            session_uuid: session.session_uuid,
            asleep,
            status: asleep ? 'asleep' : live?.activity_status || 'idle',
            unread: asleep ? unread : live?.unread === true,
            created_by_cloude: typeof live?.created_by_cloude === 'boolean' ? live.created_by_cloude : OWNED_ORIGINS.includes(session.origin ?? ''),
            host_key: session.host_key,
            agent_family: session.agent_family ?? live?.agent_family ?? null,
            claude_session_uuid: session.claude_session_uuid,
            agent_update: wire.agent_update ?? null,
            mcp_health: wire.mcp_health ?? null,
            subagents_running: live?.subagents_running ?? null,
            background_open: live?.background_open ?? null,
            timers_live: live?.timers_live ?? null,
            notifications_muted: !!wire.notifications_muted,
        },
        { surface: 'sidebar', renameable: asleep ? !!session.session_uuid : !!(live?.session?.id ?? session.live_session_id) },
    );
}
