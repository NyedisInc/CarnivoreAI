/* there is nothing */
import type { HistorySession } from '../projects-shared/history-api';
import { primaryAction } from '../projects-shared/ledger-model';

export type RowAction = 'open' | 'wake' | 'start' | 'resume' | 'restart';

export type PanelAction = RowAction | 'put-back' | 'remove';

export const isClosedRow = (s: HistorySession): boolean => s.state === 'closed' || s.state === 'removed' || s.state === 'unknown';

export function rowAction(s: HistorySession): RowAction | null {
    if (s.host_key && s.host_key !== 'local') return null;
    if (isClosedRow(s)) {
        const id = primaryAction(s).id;
        return id === 'resume' || id === 'restart' ? id : null;
    }
    if (s.state === 'running') return s.host_key === 'local' || s.live_session_id ? 'open' : null;
    return s.has_transcript === false ? 'start' : 'wake';
}
