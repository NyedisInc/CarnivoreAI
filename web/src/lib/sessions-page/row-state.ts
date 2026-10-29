import type { HistorySession } from '../projects-shared/history-api';
import type { SessionListItem } from '../sessions/types';
import { normalizeStatus } from '../status-dot';
import { needKind } from './lenses';

const KNOWN = ['working', 'working_subagent', 'question', 'notice', 'finished_unread', 'idle', 'dead', 'unknown', 'stopped'];

export function stateKeyOf(s: HistorySession, live: SessionListItem | undefined): string {
    if (s.state === 'closed' || s.state === 'removed' || s.state === 'unknown') return s.state;
    if (!live) return s.state === 'asleep' ? 'asleep' : 'running';
    if (needKind(s, { live: () => live, asleepUnread: () => false }) === 'startup') return 'startup';
    const key = normalizeStatus(live.activity_status);
    return KNOWN.includes(key) ? key : 'unknown';
}
