import { mountPanel, unmountPanel } from '../mount';
import { hostDocument, hostWindow } from '../sessions/env';
import { readFlag, writeFlag } from '../ui/prefs.svelte';
import { terminalLayout } from '../../opscenter/engine/layout.svelte';
import { PRIMARY_BIND_EVENT } from '../../opscenter/engine/primary-bind';
import { primarySessionId, sessions } from '../../opscenter/api';
import NotesDrawer from './NotesDrawer.svelte';
import { saveAll } from '../../opscenter/api/notes.svelte';
import { closeDrawer, drawerHolds, openDrawer, registerOccupant, registerOpener } from '../right-drawer/dock.svelte';

export const NOTES_BUTTON_ID = 'sessionNotesBtn';

export const NOTES_PANEL_ID = 'session-notes-panel';

const TERMINAL_SCREEN_ID = 'terminal-screen';

const NOTES_CELL = 'notes';

const WIDE = '(min-width: 1024px)';

let teardown: Array<() => void> = [];

let panelOpen = false;

function notesOpenKey(tmuxName: string): string {
    return `carnivore.notes.open.${tmuxName}`;
}

function tmuxNameFor(sessionId: string): string {
    const id = (sessionId ?? '').trim();
    if (!id) return '';
    const rows = sessions.data ?? [];
    const row = rows.find((info) => info.session?.id === id);
    return (row?.tmux_session ?? '').trim();
}

function currentTmuxName(): string {
    return tmuxNameFor(primarySessionId());
}

/* there is nothing */
function applyStoredVisibility(tmuxName: string): void {
    const name = (tmuxName ?? '').trim();
    if (!name) return;
    const wanted = readFlag(notesOpenKey(name));
    if (wide() && cellIsUp()) {
        if (panelOpen) closePanel();
    } else if (wanted && !panelOpen) {
        openPanel();
    } else if (!wanted && panelOpen) {
        closePanel();
    }
    paintButton();
}

function wide(): boolean {
    const win = hostWindow();
    if (!win || typeof win.matchMedia !== 'function') return true;
    return win.matchMedia(WIDE).matches;
}

function cellIsUp(): boolean {
    return !terminalLayout.state.layout.hidden.includes(NOTES_CELL);
}

export function notesAreOpen(): boolean {
    return drawerHolds('notes') || (wide() && cellIsUp());
}

function gridUp(): boolean {
    const host = (hostWindow() as unknown as { TerminalGridHost?: { isMounted?: () => boolean } } | null)
        ?.TerminalGridHost;
    return !!host?.isMounted?.();
}

function remember(open: boolean): void {
    const tmuxName = currentTmuxName();
    if (tmuxName) writeFlag(notesOpenKey(tmuxName), open);
}

function paintButton(): void {
    const doc = hostDocument();
    const btn = doc?.getElementById?.(NOTES_BUTTON_ID);
    if (!btn) return;
    btn.setAttribute('aria-pressed', notesAreOpen() ? 'true' : 'false');
}

function openPanel(): boolean {
    const doc = hostDocument();
    const screen = doc?.getElementById?.(TERMINAL_SCREEN_ID);
    if (!doc || !screen || typeof screen.appendChild !== 'function') return false;

    let host = doc.getElementById(NOTES_PANEL_ID);
    if (!host) {
        host = doc.createElement('div');
        host.id = NOTES_PANEL_ID;
        screen.appendChild(host);
    }
    registerOccupant('notes', { root: host, box: host, close: () => closeFromDrawer() });
    openDrawer('notes');
    const mounted = mountPanel(
        NOTES_PANEL_ID,
        NotesDrawer as never,
        {
            onClose: () => closeFromDrawer(),
            onComponent: () => openNotesAsComponent(),
            canComponent: () => wide() && gridUp(),
        } as never,
    );
    panelOpen = mounted !== null;
    if (!panelOpen) closeDrawer('notes');
    return panelOpen;
}

function closeFromDrawer(): void {
    if (!panelOpen) return;
    closePanel();
    remember(false);
    paintButton();
}

export function openNotesAsComponent(): void {
    if (panelOpen) closePanel();
    remember(false);
    if (!cellIsUp()) terminalLayout.show(NOTES_CELL);
    paintButton();
}

function closePanel(): void {
    if (panelOpen) void saveAll();
    unmountPanel(NOTES_PANEL_ID);
    const host = hostDocument()?.getElementById?.(NOTES_PANEL_ID);
    host?.remove?.();
    panelOpen = false;
    closeDrawer('notes');
}

export function toggleSessionNotes(): void {
    if (panelOpen) {
        closePanel();
        remember(false);
    } else if (wide() && cellIsUp()) {
        void saveAll();
        terminalLayout.hide(NOTES_CELL);
        remember(false);
    } else {
        openPanel();
        remember(panelOpen);
    }
    paintButton();
}

export function mountSessionNotes(): boolean {
    const doc = hostDocument();
    if (!doc || typeof doc.getElementById !== 'function') return false;
    const btn = doc.getElementById(NOTES_BUTTON_ID);
    if (!btn) return false;
    if (btn.getAttribute('data-notes-wired') === '1') return true;
    btn.setAttribute('data-notes-wired', '1');

    const onClick = (): void => toggleSessionNotes();
    btn.addEventListener('click', onClick);
    registerOpener('notes', () => {
        if (panelOpen) return;
        openPanel();
        remember(panelOpen);
        paintButton();
    });
    teardown.push(() => {
        btn.removeEventListener('click', onClick);
        btn.removeAttribute('data-notes-wired');
    });

    const win = hostWindow();
    if (win && typeof win.addEventListener === 'function') {
        const onResize = (): void => paintButton();
        win.addEventListener('resize', onResize);
        teardown.push(() => win.removeEventListener('resize', onResize));
    }

    if (win && typeof win.addEventListener === 'function') {
        const onBind = (event: Event): void => {
            const id = (event as CustomEvent<{ sessionId?: string }>).detail?.sessionId ?? '';
            applyStoredVisibility(tmuxNameFor(id));
        };
        win.addEventListener(PRIMARY_BIND_EVENT, onBind);
        teardown.push(() => win.removeEventListener(PRIMARY_BIND_EVENT, onBind));
    }

    applyStoredVisibility(currentTmuxName());
    paintButton();
    return true;
}

export function unmountSessionNotes(): void {
    closePanel();
    const undo = teardown;
    teardown = [];
    for (const step of undo) step();
}
