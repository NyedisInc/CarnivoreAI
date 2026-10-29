import { drawerController } from '../drawer/click-env';
import { activateRow } from '../drawer/row-switch';
import { usageLimitLabel } from '../led';
import { hostDocument, hostWindow } from '../sessions/env';
import { openTerminalSearchAt } from '../terminal-search/mount-search';
import { transportFor, type AgentMarkFacts } from '../sessions/agent-marks';

export interface ScrollbackMatch {
    line: number;
    occurrence_from_end: number;
    before: string;
    match: string;
    after: string;
}

export interface ScrollbackSessionHits {
    session_id: string;
    tmux_session: string;
    match_count: number;
    matches: ScrollbackMatch[];
    truncated: boolean;
    alternate_screen: boolean;
    error: string | null;
}

export interface ScrollbackSearchResult {
    query: string;
    sessions: ScrollbackSessionHits[];
    searched: number;
    total_matches: number;
    truncated: boolean;
    timed_out: number;
}

export interface SessionFacts extends AgentMarkFacts {
    label: string | null;
    name: string;
}

export interface SessionsSearchHost {
    search(query: string, signal: AbortSignal): Promise<ScrollbackSearchResult>;
    sessionFacts(): Promise<Map<string, SessionFacts>>;
    navigate(sessionId: string, tmuxName: string): Promise<boolean>;
    /* the current session */
    openFindAt(query: string, fromEnd: number): boolean;
}

export const NAVIGATE_TIMEOUT_MS = 8000;
const NAVIGATE_POLL_MS = 100;

interface ApiLike {
    call(endpoint: string, options?: Record<string, unknown>): Promise<unknown>;
    listSessions?(): Promise<unknown[]>;
    getSession?(id: string, opts?: Record<string, unknown>): Promise<unknown>;
}
interface TerminalLike {
    term?: unknown;
    _sessionId?(): string | null;
}
interface NavGenLike {
    begin(label: string): unknown;
    keep(token: unknown, label: string): boolean;
}
interface Globals {
    API?: ApiLike;
    TerminalController?: TerminalLike;
    NavigationGeneration?: NavGenLike;
    App?: { currentScreen?: string; returnToExistingTerminal?(info: unknown): Promise<void> };
}

function globals(): Globals {
    return (hostWindow() as unknown as Globals | undefined) ?? {};
}

function currentSessionId(): string | null {
    const ctl = globals().TerminalController;
    if (!ctl || typeof ctl._sessionId !== 'function' || !ctl.term) return null;
    try {
        return ctl._sessionId();
    } catch (err) {
        console.warn('SessionsSearch: could not read the current session', err);
        return null;
    }
}

export function terminalShown(): boolean {
    const screen = globals().App?.currentScreen;
    return screen === undefined || screen === 'terminal';
}

export function waitForSession(
    sessionId: string,
    timeoutMs: number,
    read: () => string | null = currentSessionId,
): Promise<boolean> {
    const deadline = Date.now() + timeoutMs;
    return new Promise((resolve) => {
        const check = (): void => {
            if (read() === sessionId) resolve(true);
            else if (Date.now() >= deadline) resolve(false);
            else setTimeout(check, NAVIGATE_POLL_MS);
        };
        check();
    });
}

async function switchTo(sessionId: string, tmuxName: string, rejoin = false): Promise<void> {
    const g = globals();
    const doc = hostDocument();
    const escaped = typeof CSS !== 'undefined' && CSS.escape ? CSS.escape(tmuxName) : tmuxName;
    const row = doc?.querySelector?.(`.session-sidebar-row[data-name="${escaped}"]`) ?? null;
    const ctl = drawerController();
    if (!rejoin && row && ctl) {
        await activateRow(ctl, row);
        return;
    }
    if (!g.API?.getSession || !g.App?.returnToExistingTerminal) {
        throw new Error('the session switch is not available on this page');
    }
    const nav = g.NavigationGeneration?.begin('session:' + tmuxName) ?? null;
    const info = await g.API.getSession(sessionId, { includeScrollback: true });
    if (g.NavigationGeneration && !g.NavigationGeneration.keep(nav, 'search jump to ' + tmuxName)) return;
    if (info) await g.App.returnToExistingTerminal(info);
}

function factsFrom(row: Record<string, unknown>): [string, SessionFacts] | null {
    const inner = (row.session ?? {}) as Record<string, unknown>;
    const id = typeof inner.id === 'string' ? inner.id : null;
    if (!id) return null;
    const str = (v: unknown): string | null => (typeof v === 'string' ? v : null);
    const name = str(row.tmux_session) ?? str(inner.tmux_session) ?? '';
    return [
        id,
        {
            label: str(row.label),
            name,
            family: str(row.agent_family),
            status: str(row.activity_status),
            unread: row.unread === true,
            startupGate: str(row.startup_gate),
            statusSource: str(row.status_source),
            activityHint: str(row.activity_hint),
            usageLimit: usageLimitLabel(row),
            transport: transportFor(name),
        },
    ];
}

export function browserSessionsSearchHost(): SessionsSearchHost {
    return {
        async search(query, signal) {
            const api = globals().API;
            if (!api) throw new Error('the API client is not loaded');
            const q = encodeURIComponent(query);
            return (await api.call(`/sessions/scrollback-search?q=${q}`, { signal })) as ScrollbackSearchResult;
        },
        async sessionFacts() {
            const out = new Map<string, SessionFacts>();
            const api = globals().API;
            if (!api?.listSessions) return out;
            try {
                const rows = await api.listSessions();
                for (const row of rows ?? []) {
                    const pair = factsFrom(row as Record<string, unknown>);
                    if (pair) out.set(pair[0], pair[1]);
                }
            } catch (err) {
                console.warn('SessionsSearch: the session list could not be read', err);
            }
            return out;
        },
        async navigate(sessionId, tmuxName) {
            const attached = currentSessionId() === sessionId;
            if (!attached || !terminalShown()) await switchTo(sessionId, tmuxName, attached);
            return waitForSession(sessionId, NAVIGATE_TIMEOUT_MS);
        },
        openFindAt(query, fromEnd) {
            return openTerminalSearchAt(query, fromEnd);
        },
    };
}
