import { hasDesktopCapability, desktopBridge, type FolderTargetResult } from '../settings-page/desktop-bridge';
import { rowFor } from '../../opscenter/cells/terminal-viewer/meta';
import type { SessionInfo } from '../../opscenter/api/types';
import { showToast } from '../widgets-page/undo-toast';
import { t } from '../i18n/index.svelte';

export function folderTargetId(target: 'session' | 'project', sessionId: string | null, rows: SessionInfo[] | null): string | null {
    if (!sessionId || sessionId.startsWith('remote:')) return null;
    const row = rowFor(rows, sessionId);
    if (!row || (row.host_key && row.host_key !== 'local')) return null;
    if (target === 'session') return sessionId;
    return typeof row.project_id === 'number' ? `project:${row.project_id}` : null;
}

async function run(method: 'revealById' | 'openInEditor', id: string, failedKey: string, surfaceKey: string): Promise<void> {
    if (!hasDesktopCapability(method)) return;
    const call = desktopBridge()?.[method];
    if (!call) return;
    let reason: string | null = null;
    try {
        const answer: FolderTargetResult = await call(id);
        if (answer && !answer.ok && answer.reason === 'failed') reason = answer.error ?? answer.reason;
    } catch (error) {
        reason = error instanceof Error ? error.message : String(error);
    }
    if (reason !== null) showToast({ kind: 'failed', text: t(failedKey, { reason }), surface: t(surfaceKey) });
}

export function revealInFinder(id: string): Promise<void> {
    return run('revealById', id, 'desktop.menu.reveal_failed', 'desktop.menu.reveal');
}

export function openInEditor(id: string): Promise<void> {
    return run('openInEditor', id, 'desktop.menu.editor_failed', 'desktop.menu.open_in_editor');
}
