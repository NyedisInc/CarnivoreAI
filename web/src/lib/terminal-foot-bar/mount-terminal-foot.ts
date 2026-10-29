/* flex: 0 0 auto`
 * so `#terminal-grid`'s own `flex: 1` shrinks by exactly this bar's height; */
import { ensurePanel, panelInstance, unmountPanel } from '../mount';
import { hostDocument, hostWindow } from '../sessions/env';
import { PRIMARY_BIND_EVENT } from '../../opscenter/engine/primary-bind';
import { primarySessionId } from '../../opscenter/api';
import TerminalFootHost from './TerminalFootHost.svelte';

export const TERMINAL_FOOT_CONTAINER_ID = 'terminal-foot-bar';

interface TerminalFootHandle {
    setSession?: (id: string) => void;
}

interface ThemeHost {
    Themes?: { applyScopeTo(el: HTMLElement, ctx: { pinnedTheme: string | null }): () => void };
    ThemeNavigation?: { resolvePinnedTheme(session: unknown): string | null };
    TerminalController?: { _currentSession?: unknown };
    TerminalLayout?: { requestFit(reason: string): void };
}

let teardown: Array<() => void> = [];

let releaseTheme: (() => void) | null = null;

function legacyPaneActive(doc: Document): boolean {
    if (!doc.getElementById('terminal-container')) return false;
    return !doc.querySelector('#terminal-grid .oc-surface');
}

function ensureMounted(): TerminalFootHandle | null {
    const doc = hostDocument();
    if (!doc || typeof doc.getElementById !== 'function') return null;
    if (!doc.getElementById(TERMINAL_FOOT_CONTAINER_ID)) return null;
    return ensurePanel(
        TERMINAL_FOOT_CONTAINER_ID, TerminalFootHost as never, {},
    ) as TerminalFootHandle | null;
}

function releaseThemeScope(): void {
    if (!releaseTheme) return;
    releaseTheme();
    releaseTheme = null;
}

function scopeTheme(): void {
    releaseThemeScope();
    const doc = hostDocument();
    const el = doc?.getElementById?.(TERMINAL_FOOT_CONTAINER_ID);
    const win = hostWindow() as unknown as ThemeHost | undefined;
    if (!el || !win?.Themes || typeof win.Themes.applyScopeTo !== 'function') return;
    const nav = win.ThemeNavigation;
    const pin = nav && typeof nav.resolvePinnedTheme === 'function'
        ? nav.resolvePinnedTheme(win.TerminalController?._currentSession)
        : null;
    releaseTheme = win.Themes.applyScopeTo(el, { pinnedTheme: pin });
}

function requestFit(): void {
    const win = hostWindow() as unknown as ThemeHost | undefined;
    win?.TerminalLayout?.requestFit(TERMINAL_FOOT_CONTAINER_ID);
}

function apply(sessionId: string): void {
    const doc = hostDocument();
    const active = !!doc && legacyPaneActive(doc);
    const handle = ensureMounted();
    const shown = active ? (sessionId ?? '').trim() : '';
    if (handle && typeof handle.setSession === 'function') handle.setSession(shown);
    if (shown) scopeTheme();
    else releaseThemeScope();
    requestFit();
}

export function mountTerminalFoot(): boolean {
    const doc = hostDocument();
    if (!doc || typeof doc.getElementById !== 'function') return false;
    if (!doc.getElementById(TERMINAL_FOOT_CONTAINER_ID)) return false;
    if (teardown.length) return true;

    const win = hostWindow();
    if (win && typeof win.addEventListener === 'function') {
        const onBind = (event: Event): void => {
            const id = (event as CustomEvent<{ sessionId?: string }>).detail?.sessionId ?? '';
            apply(id);
        };
        win.addEventListener(PRIMARY_BIND_EVENT, onBind);
        teardown.push(() => win.removeEventListener(PRIMARY_BIND_EVENT, onBind));
    }

    if (win && typeof win.matchMedia === 'function') {
        const mq = win.matchMedia('(min-width: 1024px)');
        const onWidthChange = (): void => {
            win.setTimeout(() => apply(primarySessionId()), 60);
        };
        if (typeof mq.addEventListener === 'function') {
            mq.addEventListener('change', onWidthChange);
            teardown.push(() => mq.removeEventListener('change', onWidthChange));
        }
    }

    apply(primarySessionId());
    return true;
}

export function unmountTerminalFoot(): void {
    releaseThemeScope();
    unmountPanel(TERMINAL_FOOT_CONTAINER_ID);
    const undo = teardown;
    teardown = [];
    for (const step of undo) step();
}
