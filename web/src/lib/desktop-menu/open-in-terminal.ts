import { hasDesktopCapability, desktopBridge } from '../settings-page/desktop-bridge';
import { showToast } from '../widgets-page/undo-toast';
import { t } from '../i18n/index.svelte';

export function canOpenInTerminal(sessionId: string, hostKey: string | null | undefined, tmuxName: string | null | undefined): boolean {
    if (!hasDesktopCapability('openInTerminal')) return false;
    if (!sessionId || sessionId.startsWith('remote:')) return false;
    if (hostKey && hostKey !== 'local') return false;
    return !!tmuxName;
}

export async function openInTerminal(sessionId: string): Promise<void> {
    const open = desktopBridge()?.openInTerminal;
    if (!open || !sessionId) return;
    let text: string | null = null;
    try {
        const answer = await open(sessionId);
        if (answer && !answer.opened && answer.reason !== 'cancelled') {
            text = answer.reason === 'not_running'
                ? t('desktop.menu.open_in_terminal_not_running')
                : t('desktop.menu.open_in_terminal_failed', { reason: answer.error ?? answer.reason });
        }
    } catch (error) {
        text = t('desktop.menu.open_in_terminal_failed', { reason: error instanceof Error ? error.message : String(error) });
    }
    if (text !== null) showToast({ kind: 'failed', text, surface: t('desktop.menu.open_in_terminal') });
}
