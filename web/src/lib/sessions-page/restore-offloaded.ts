import { promptRestore } from '../offload-prompt/offload-prompt';
import type { HistorySession } from '../projects-shared/history-api';

export async function restoreOffloadedSession(s: HistorySession, onRestored: () => void): Promise<boolean> {
    const done = await promptRestore({ sessionUuid: s.session_uuid, label: s.label ?? s.title });
    if (done) onRestored();
    return done;
}
