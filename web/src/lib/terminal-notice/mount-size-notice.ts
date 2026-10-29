import { ensurePanel, panelInstance } from '../mount';
import { hostDocument } from '../sessions/env';
import TerminalSizeNotice from './TerminalSizeNotice.svelte';

export const SIZE_NOTICE_CONTAINER_ID = 'terminal-size-notice';

interface SizeNoticeHandle {
    setGrid?: (next: { cols: number; rows: number } | null) => void;
}

function ensureMounted(): SizeNoticeHandle | null {
    const doc = hostDocument();
    if (!doc || typeof doc.getElementById !== 'function') return null;
    if (!doc.getElementById(SIZE_NOTICE_CONTAINER_ID)) return null;
    return ensurePanel(
        SIZE_NOTICE_CONTAINER_ID, TerminalSizeNotice as never, {},
    ) as SizeNoticeHandle | null;
}

export function showTerminalSizeNotice(cols: number, rows: number): void {
    const handle = ensureMounted();
    if (handle && typeof handle.setGrid === 'function') handle.setGrid({ cols, rows });
}

export function clearTerminalSizeNotice(): void {
    const handle = panelInstance(SIZE_NOTICE_CONTAINER_ID) as SizeNoticeHandle | null;
    if (handle && typeof handle.setGrid === 'function') handle.setGrid(null);
}
