import { hostDocument, hostWindow } from '../sessions/env';
import type {
    HistoryApi,
    PromptScanApi,
    SearchEngineApi,
    TermLike,
} from './types';

export const TERMINAL_CREATED_EVENT = 'terminal-created';

export interface ControllerLike {
    term?: TermLike | null;
    _sessionId?(): string | null;
    _currentSession?: unknown;
}

export interface SearchHost {
    term(): TermLike | null;
    onTerminal(listener: () => void): () => void;
    sessionId(): string | null;
    agentFamily(): string | null;
    engine(): SearchEngineApi | null;
    history(): HistoryApi | null;
    promptScan(): PromptScanApi | null;
    isRule(): ((text: string) => boolean) | undefined;
    promptTexts?(): Promise<string[] | null>;
    modalOpen(): boolean;
    terminalScreenActive(): boolean;
    focusTerm(): void;
}

interface SearchGlobals {
    TerminalController?: ControllerLike;
    TerminalSearchEngine?: SearchEngineApi & { create?(): SearchEngineApi };
    TerminalHistory?: HistoryApi;
    TerminalPromptScan?: PromptScanApi;
    AltScreenScroll?: { isRule?: (text: string) => boolean };
    ModalStack?: { depth?(): number };
    API?: { call(endpoint: string, options?: Record<string, unknown>): Promise<unknown> };
    ListingPush?: { rows?(name: string): Array<Record<string, unknown>> | null };
}

export function scannerForFamily(family: string | null, api: PromptScanApi | null): PromptScanApi | null {
    if (family === 'claude') return api;
    if (family === 'codex' && api) {
        return { ...api, scan: (buffer, opts) => api.scan(buffer, { ...opts, family: 'codex' }) };
    }
    return null;
}

function globals(): SearchGlobals {
    return (hostWindow() as unknown as SearchGlobals) ?? {};
}

export function onAlternateScreen(term: TermLike | null): boolean {
    try {
        return term?.buffer?.active?.type === 'alternate';
    } catch {
        return false;
    }
}

export function browserSearchHost(controller?: ControllerLike): SearchHost {
    const ctl = (): ControllerLike | null => controller ?? globals().TerminalController ?? null;
    let cellEngine: SearchEngineApi | null = null;
    const agentFamily = (): string | null => {
        const s = ctl()?._currentSession as { agent_family?: unknown; id?: unknown } | null | undefined;
        if (s && typeof s.agent_family === 'string') return s.agent_family;
        const id = s && typeof s.id === 'string' ? s.id : null;
        const rows = id ? globals().ListingPush?.rows?.('list') : null;
        const row = rows?.find((r) => (r.session as { id?: unknown } | undefined)?.id === id);
        return row && typeof row.agent_family === 'string' ? row.agent_family : null;
    };
    return {
        term: () => ctl()?.term ?? null,
        onTerminal: (listener: () => void): (() => void) => {
            const win = hostWindow();
            if (!win || typeof win.addEventListener !== 'function') return () => {};
            win.addEventListener(TERMINAL_CREATED_EVENT, listener);
            return () => win.removeEventListener(TERMINAL_CREATED_EVENT, listener);
        },
        sessionId: () => {
            const c = ctl();
            if (!c || typeof c._sessionId !== 'function') return null;
            try {
                return c._sessionId();
            } catch {
                return null;
            }
        },
        agentFamily,
        engine: () => {
            const engine = globals().TerminalSearchEngine;
            if (!controller) return engine ?? null;
            return cellEngine ??= engine?.create?.() ?? null;
        },
        history: () => {
            const history = globals().TerminalHistory;
            if (!history) return null;
            return controller ? {
                ensureLoaded: (term, sessionId) => history.ensureLoaded(term, sessionId, controller),
            } : history;
        },
        promptScan: () => scannerForFamily(agentFamily(), globals().TerminalPromptScan ?? null),
        promptTexts: async () => {
            const c = ctl();
            const id = c && typeof c._sessionId === 'function' ? c._sessionId() : null;
            const api = globals().API;
            if (!id || !api) return null;
            try {
                const res = (await api.call(`/sessions/${encodeURIComponent(id)}/prompt-texts`)) as
                    { prompts?: unknown } | null;
                return Array.isArray(res?.prompts) ? (res.prompts as string[]) : null;
            } catch {
                return null;
            }
        },
        isRule: () => {
            const alt = globals().AltScreenScroll;
            return typeof alt?.isRule === 'function' ? alt.isRule : undefined;
        },
        modalOpen: () => {
            const active = hostDocument()?.activeElement;
            if (active && typeof active.closest === 'function' && active.closest('[data-modal]')) return true;
            const ms = globals().ModalStack;
            if (!ms || typeof ms.depth !== 'function') return false;
            try {
                return ms.depth() > 0;
            } catch {
                return false;
            }
        },
        terminalScreenActive: () => {
            const el = hostDocument()?.getElementById('terminal-screen');
            const home = hostDocument()?.getElementById('launchpad-screen');
            return !!el?.classList?.contains('active') && !home?.classList?.contains('active');
        },
        focusTerm: () => {
            try {
                ctl()?.term?.focus?.();
            } catch (err) {
                console.warn('TerminalSearch: could not refocus the pane', err);
            }
        },
    };
}
