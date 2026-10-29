/* is gone with */
import { mountPanel, unmountPanel } from '../lib/mount';
import TerminalSurface from './TerminalSurface.svelte';
import ComponentsPopover from './engine/ComponentsPopover.svelte';
import { terminalLayout } from './engine/layout.svelte';
import { releaseHeldPane } from './cells/terminal/adopt';
import { bindPrimary, watchPrimaryBind } from './engine/primary-bind';
import { primarySessionId, primaryTmuxEpoch, primaryTmuxName } from './api/host';
import { noteSurface } from './layouts/page.svelte';
import { subscribe, openSession } from './api';
import { t } from '../lib/i18n/index.svelte';

const TERMINAL_COMPONENTS_ID = 'terminal-components';

/* nobody is looking at */
let stopBindWatch: (() => void) | null = null;

function onAgentOpened(frame: { session_id?: string; name?: string }): void {
    const id = typeof frame.session_id === 'string' ? frame.session_id : '';
    if (!id || globalThis.innerWidth >= 1024) return;
    const toast = (globalThis as { ToastManager?: { add(item: Record<string, unknown>): void } }).ToastManager;
    toast?.add({ id: `agent-open:${id}`, session_id: null,
        session_name: frame.name || id, session_label: frame.name || id,
        kind: 'AgentOpen',
        title: t('agent.opened.title'), body: t('agent.opened.open'), local: true,
        on_open: () => openSession(id, null) });
}

subscribe('agent.spawned', onAgentOpened);
subscribe('agent.forked', onAgentOpened);

export function mountTerminalGrid(containerId: string): boolean {
    if (!stopBindWatch) stopBindWatch = watchPrimaryBind(terminalLayout);
    bindPrimary(terminalLayout, primarySessionId(), primaryTmuxName(), primaryTmuxEpoch());
    noteSurface('grid', true);
    return mountPanel(containerId, TerminalSurface) !== null;
}

export function openTerminalComponents(anchor: HTMLElement | null): boolean {
    return (
        mountPanel(TERMINAL_COMPONENTS_ID, ComponentsPopover, {
            anchor,
            store: terminalLayout,
            onClose: () => closeTerminalComponents(),
        }) !== null
    );
}

export function closeTerminalComponents(): boolean {
    return unmountPanel(TERMINAL_COMPONENTS_ID);
}

export function terminalComponentsOpen(): boolean {
    if (typeof document === 'undefined') return false;
    const host = document.getElementById(TERMINAL_COMPONENTS_ID);
    return !!host && host.childElementCount > 0;
}

export function unmountTerminalGrid(containerId: string): boolean {
    closeTerminalComponents();
    releaseHeldPane();
    if (stopBindWatch) {
        stopBindWatch();
        stopBindWatch = null;
    }
    noteSurface('grid', false);
    return unmountPanel(containerId);
}
