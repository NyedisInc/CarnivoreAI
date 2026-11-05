import { inputFocus } from '../../opscenter/lib/input-focus.svelte';
import { activeTerminalSessionId } from '../../opscenter/lib/active-terminal';
import { PRIMARY_SLOT } from '../../opscenter/engine/model';
import { primarySessionId } from '../../opscenter/api/host';
import { PRIMARY_BIND_EVENT } from '../../opscenter/engine/primary-bind';

export const QUIET_WATCHED_FIELD = 'notify_quiet_watched';
export const WATCHED_EVENT = 'carnivore:watched-session';

interface Bridge {
    read(field: string, localReader: () => unknown): unknown;
    write(field: string, value: unknown, localWriter: () => void): Promise<unknown>;
    follow?(field: string, apply: (value: unknown) => void): () => void;
}

function bridge(): Bridge | null {
    const found = (globalThis as { PreferenceBridge?: Bridge }).PreferenceBridge;
    return found && typeof found.read === 'function' ? found : null;
}

export const quietWatched = $state({ on: true });

export function refreshQuietWatched(): boolean {
    quietWatched.on = bridge()?.read(QUIET_WATCHED_FIELD, () => true) !== false;
    return quietWatched.on;
}

const SAVED = new Set(['committed', 'unchanged']);

export async function saveQuietWatched(on: boolean): Promise<string | null> {
    const found = bridge();
    if (!found) return 'unavailable';
    const result = (await found.write(QUIET_WATCHED_FIELD, on, () => {})) as { status?: string; detail?: string } | null;
    const status = result && typeof result.status === 'string' ? result.status : '';
    refreshQuietWatched();
    recompute(true);
    if (SAVED.has(status)) return null;
    return (result && result.detail) || status || 'unavailable';
}

export interface WatchedDeps {
    doc?: Document;
    win?: Window;
    sessionOf?: () => string;
}

function focusedTerminalSession(): string {
    const owner = inputFocus.owner;
    if (owner && owner.startsWith('terminal:') && owner !== PRIMARY_SLOT) return activeTerminalSessionId(owner);
    return primarySessionId();
}

export function computeWatched(doc: Document, sessionOf: () => string = focusedTerminalSession): string {
    if (!quietWatched.on || doc.visibilityState !== 'visible' || !doc.hasFocus()) return '';
    const active = doc.activeElement;
    if (!active || typeof active.closest !== 'function' || !active.closest('.xterm')) return '';
    return sessionOf() || '';
}

let current = '';
let recompute: (force: boolean) => void = () => {};

export function watchedSessionId(): string {
    return current;
}

export function startWatchedSession(deps: WatchedDeps = {}): () => void {
    const doc = deps.doc ?? document;
    const win = deps.win ?? window;
    const sessionOf = deps.sessionOf ?? focusedTerminalSession;
    refreshQuietWatched();
    const settle = (force: boolean): void => {
        const next = computeWatched(doc, sessionOf);
        if (next === current && !force) return;
        current = next;
        const desktop = (win as unknown as { carnivoreDesktop?: { watching?: (id: string) => void } }).carnivoreDesktop;
        if (desktop && typeof desktop.watching === 'function') desktop.watching(next);
        win.dispatchEvent(new CustomEvent(WATCHED_EVENT, { detail: next }));
    };
    const update = (): void => settle(false);
    const later = (): void => queueMicrotask(update);
    recompute = settle;
    doc.addEventListener('focusin', update);
    doc.addEventListener('focusout', later);
    doc.addEventListener('visibilitychange', update);
    win.addEventListener('focus', update);
    win.addEventListener('blur', later);
    win.addEventListener(PRIMARY_BIND_EVENT, later);
    const unfollow = bridge()?.follow?.(QUIET_WATCHED_FIELD, () => { refreshQuietWatched(); settle(true); }) ?? (() => {});
    (globalThis as { NotifyQuietWatched?: unknown }).NotifyQuietWatched = Object.freeze({
        on: () => quietWatched.on,
        current: () => current,
    });
    update();
    return () => {
        doc.removeEventListener('focusin', update);
        doc.removeEventListener('focusout', later);
        doc.removeEventListener('visibilitychange', update);
        win.removeEventListener('focus', update);
        win.removeEventListener('blur', later);
        win.removeEventListener(PRIMARY_BIND_EVENT, later);
        unfollow();
        recompute = () => {};
    };
}
