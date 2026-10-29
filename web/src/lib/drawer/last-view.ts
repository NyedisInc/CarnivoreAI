import { readKey, writeKey } from './storage';
import { pageWindow } from './env';
import { layouts } from '../layouts-bridge/api.svelte';
import { openSession } from '../../opscenter/api/host';

export const LAST_VIEW_KEY = 'carnivore.session.lastView';

export type LastView =
    | { kind: 'session'; sessionId: string; tmuxName: string }
    | { kind: 'layout'; uuid: string };

interface RowLike {
    name?: string;
    session_id?: string | null;
    asleep?: boolean;
    status?: string;
}

export interface RestoreDeps {
    screen: () => string | undefined;
    rows: () => RowLike[];
    hasLayout: (uuid: string) => boolean | null;
    openSession: (sessionId: string, tmuxName: string) => boolean;
    openLayout: (uuid: string) => unknown;
}

export function rememberLastView(view: LastView): void {
    try {
        writeKey(LAST_VIEW_KEY, JSON.stringify(view));
    } catch {
    }
}

export function readLastView(): LastView | null {
    try {
        const raw = readKey(LAST_VIEW_KEY);
        if (!raw) return null;
        const v = JSON.parse(raw) as Partial<LastView> | null;
        if (v && v.kind === 'layout' && typeof v.uuid === 'string' && v.uuid) return { kind: 'layout', uuid: v.uuid };
        if (v && v.kind === 'session') {
            const sessionId = typeof v.sessionId === 'string' ? v.sessionId : '';
            const tmuxName = typeof v.tmuxName === 'string' ? v.tmuxName : '';
            if (sessionId || tmuxName) return { kind: 'session', sessionId, tmuxName };
        }
    } catch {
    }
    return null;
}

export function forgetLastView(): void {
    try {
        writeKey(LAST_VIEW_KEY, '');
    } catch {
    }
}

export function watchSessionDestroyed(win: EventTarget = pageWindow() as unknown as EventTarget): void {
    win.addEventListener('session-destroyed', () => {
        if (readLastView()?.kind === 'session') forgetLastView();
    });
    win.addEventListener('cloude:primary-session-gone', (ev) => {
        const gone = (ev as CustomEvent<{ tmuxName?: string; sessionId?: string } | null>).detail;
        const rec = readLastView();
        if (!gone || rec?.kind !== 'session') return;
        if ((gone.tmuxName && gone.tmuxName === rec.tmuxName) || (gone.sessionId && gone.sessionId === rec.sessionId)) {
            forgetLastView();
        }
    });
}

const liveDeps: RestoreDeps = {
    screen: () => (pageWindow() as { App?: { currentScreen?: string } }).App?.currentScreen,
    rows: () => (pageWindow() as { SessionSidebar?: { _rows?: RowLike[] } }).SessionSidebar?._rows ?? [],
    hasLayout: (uuid) => {
        const held = layouts.data;
        return held === null ? null : held.some((l) => l.layout_uuid === uuid);
    },
    openSession,
    openLayout: (uuid) =>
        (pageWindow() as { CloudeWeb?: { layoutPage?: { openLayout?: (u: string) => unknown } } })
            .CloudeWeb?.layoutPage?.openLayout?.(uuid),
};

export function restoreLastView(deps: RestoreDeps = liveDeps): boolean {
    if (deps.screen() !== 'launchpad') return false;
    const view = readLastView();
    if (!view) return false;
    if (view.kind === 'layout') {
        if (deps.hasLayout(view.uuid) === false) {
            forgetLastView();
            return false;
        }
        void deps.openLayout(view.uuid);
        return true;
    }
    const rows = deps.rows();
    if (rows.length === 0) return false;
    const row = rows.find((r) => !r.asleep && r.status !== 'dead' && r.status !== 'closed' && (view.sessionId ? r.session_id === view.sessionId : r.name === view.tmuxName));
    if (!row) {
        forgetLastView();
        return false;
    }
    return deps.openSession(row.session_id ?? view.sessionId, row.name ?? view.tmuxName);
}
