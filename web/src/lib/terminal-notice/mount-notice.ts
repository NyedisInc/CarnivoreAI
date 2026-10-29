import { ensurePanel } from '../mount';
import { hostDocument } from '../sessions/env';
import TerminalStartupNotice from './TerminalStartupNotice.svelte';

export const NOTICE_CONTAINER_ID = 'terminal-startup-notice';

interface NoticeHandle {
    setFailed?: (next: boolean) => void;
}

function ensureMounted(): NoticeHandle | null {
    const doc = hostDocument();
    if (!doc || typeof doc.getElementById !== 'function') return null;
    const target = doc.getElementById(NOTICE_CONTAINER_ID);
    if (!target) return null;
    return ensurePanel(NOTICE_CONTAINER_ID, TerminalStartupNotice as never, {}) as NoticeHandle | null;
}

export function showTerminalStartupNotice(failed: boolean): void {
    const handle = ensureMounted();
    if (handle && typeof handle.setFailed === 'function') handle.setFailed(failed);
}

export function clearTerminalStartupNotice(): void {
    showTerminalStartupNotice(false);
}
