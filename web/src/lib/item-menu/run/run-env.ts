import { drawerEnv } from '../../drawer/env';
import type { RowMenuCtx } from '../row-context';

export interface SessionRecord {
    tmux_name?: string;
    session_uuid?: string;
    working_dir?: string;
    title?: string;
    archived_at?: string | null;
    tmux_created_epoch?: number;
}

export interface ProjectRow {
    id?: unknown;
    name?: string;
    path?: string;
}

export interface PromptOptions {
    title: string;
    label: string;
    defaultValue: string;
    confirmLabel: string;
    cancelLabel: string;
}

export interface RowMenuBridge {
    setMuteOverride(name: string, muted: boolean): void;
    shiftHeld(): boolean;
    runPlugin?(id: string, ctx: RowMenuCtx): Promise<boolean>;
}

export interface CloudeWebRun {
    openForkPicker?: (sessionId: string, label: string) => void;
    launchpad?: { createConsoleSession?: (o: { workingDir: string }) => Promise<unknown> };
    scheduleThis?: (o: { kind: string; id: string }) => void;
    showPath?: (path: string, label: string) => Promise<unknown>;
    rowMenu?: RowMenuBridge;
    addToMenu?: {
        openForLayout?(anchor: Element, layoutUuid: string | undefined, opts?: unknown): void;
        openForSession?(anchor: Element, name: string, sessionUuid: string | null, opts?: unknown): void;
    };
    sendTo?: { openForSession(anchor: Element, o: { sessionUuid: string; name: string; projectName: () => Promise<string | null> }): void };
    moveToFolder?: { open(o: { sessionUuid: string; name: string }): void };
    autoSleep?: { setKeepAwake?(name: string, on: boolean): Promise<unknown>; isKeptAwake(name: string): boolean | null };
}

export interface RunEnv {
    CloudeI18n?: { t(key: string, params?: Record<string, string>): string };
    Launchpad?: { showError?(text: string): void; selectProject?(o: { name: string; path: string; launch_from?: { kind: 'session'; name: string; pinned: boolean } }): Promise<unknown> };
    SessionSidebarArrangement?: { isPinned?(name: string): boolean };
    API?: {
        listSessionRecords?(): Promise<SessionRecord[]>;
        getProjects?(): Promise<ProjectRow[]>;
        renameSession(id: string, label: string): Promise<unknown>;
        call(path: string, init: { method: string; body: unknown }): Promise<{ muted?: unknown } | undefined>;
        setSessionUnread(name: string, unread: boolean): Promise<unknown>;
    };
    TextPromptModal?: { open?(o: PromptOptions): Promise<string | null> };
    SessionLabel?: { validate?(raw: string): { ok: boolean; value?: string; reason?: string } };
    SessionSidebar?: { _rows?: { asleep?: boolean; session_uuid?: string; session_id?: string }[]; _lastSig?: string | null; repaint?(): void };
    SessionRowActions?: { ATTR_ACTION: string; ATTR_NAME: string; ACTION_CLOSE: string };
    CopyCompat?: { copyText?(text: string): Promise<{ ok?: boolean } | undefined> };
    CloudeWeb?: CloudeWebRun;
}

export function runEnv(): RunEnv {
    return drawerEnv() as RunEnv;
}

let navSeq = 0;

const NAV_EVENTS: readonly string[] = ['session-created', 'popstate', 'hashchange'];

if (typeof window !== 'undefined') {
    NAV_EVENTS.forEach((evt) => window.addEventListener(evt, () => { navSeq += 1; }));
}

export function navToken(): number {
    return navSeq;
}

export function tr(key: string, params?: Record<string, string>): string {
    const i18n = runEnv().CloudeI18n;
    return i18n && typeof i18n.t === 'function' ? i18n.t(key, params) : key;
}

export function say(_ctx: unknown, text: string): void {
    const lp = runEnv().Launchpad;
    if (lp && typeof lp.showError === 'function') { lp.showError(text); return; }
    console.warn('[SessionRowMenuActions]', text);
}

export function rowElementFor(ctx: { name?: string } | null | undefined): Element | null {
    if (!ctx || !ctx.name || typeof document.querySelector !== 'function') return null;
    return document.querySelector(`.session-sidebar-row[data-name="${CSS.escape(ctx.name)}"]`);
}

/* could not be read */
export async function recordFor(tmuxName: string): Promise<SessionRecord | null> {
    const api = runEnv().API;
    if (!tmuxName || !api || typeof api.listSessionRecords !== 'function') return null;
    let rows: SessionRecord[];
    try {
        rows = await api.listSessionRecords();
    } catch (err) {
        console.error('[SessionRowMenuActions] could not read session records:', err);
        return null;
    }
    if (!Array.isArray(rows)) return null;
    let best: SessionRecord | null = null;
    for (const r of rows) {
        if (!r || r.tmux_name !== tmuxName || r.archived_at) continue;
        if (!best) { best = r; continue; }
        const a = typeof r.tmux_created_epoch === 'number' ? r.tmux_created_epoch : -1;
        const b = typeof best.tmux_created_epoch === 'number' ? best.tmux_created_epoch : -1;
        if (a > b) best = r;
    }
    return best;
}

export async function projectHomePathFor(ctx: RowMenuCtx): Promise<string | null> {
    const api = runEnv().API;
    if (ctx.projectId != null && api && typeof api.getProjects === 'function') {
        try {
            const projects = await api.getProjects();
            if (Array.isArray(projects)) {
                for (const p of projects) {
                    if (p && p.id === ctx.projectId && p.path) return p.path;
                }
            }
        } catch (err) {
            console.error('[SessionRowMenuActions] could not read projects:', err);
        }
    }
    const record = await recordFor(ctx.name);
    return (record && record.working_dir) || null;
}
