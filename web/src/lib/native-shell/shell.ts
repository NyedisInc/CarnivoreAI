import { activeGlobalThemeId } from '../themes-page/global-theme';
import { primaryTmuxName } from '../../opscenter/api/host';
import { PRIMARY_BIND_EVENT } from '../../opscenter/engine/primary-bind';
import { WATCHED_EVENT, quietWatched } from '../notifications/quiet-watched.svelte';

export const SHELL_VERSION = 1;

export type ToNative =
    | { type: 'ready' }
    | { type: 'registerPush' }
    | { type: 'pushRegistered'; id: string }
    | { type: 'theme'; id: string }
    | { type: 'viewing'; session: string }
    | { type: 'speechStart' }
    | { type: 'speechStop' }
    | { type: 'speechCancel' };

export type FromNative =
    | { type: 'pushToken'; token: string; environment: string; payload_key: string; bundle_id: string; app_version: string }
    | { type: 'pushFailed'; reason: string }
    | { type: 'openPath'; path: string }
    | { type: 'speech'; kind: 'text' | 'end' | 'error'; text: string; reason: string };

interface ShellWindow {
    carnivoreShell?: { version?: unknown; platform?: unknown; receive?: (message: unknown) => void };
    webkit?: { messageHandlers?: { carnivore?: { postMessage?: (message: unknown) => void } } };
    location: Location;
}

const win = (): ShellWindow => globalThis as unknown as ShellWindow;

export function inNativeShell(): boolean {
    const shell = win().carnivoreShell;
    return (
        shell?.version === SHELL_VERSION && typeof win().webkit?.messageHandlers?.carnivore?.postMessage === 'function'
    );
}

export function postToNative(message: ToNative): boolean {
    if (!inNativeShell()) return false;
    win().webkit!.messageHandlers!.carnivore!.postMessage!({ v: SHELL_VERSION, ...message });
    return true;
}

export function isSafePath(path: unknown): path is string {
    return typeof path === 'string' && /^\/(?![/\\])[^\\\u0000-\u001f\u007f]*$/.test(path);
}

type Listener = (message: FromNative) => void;
const listeners = new Set<Listener>();

export function onNativeMessage(listener: Listener): () => void {
    listeners.add(listener);
    return () => listeners.delete(listener);
}

export function parseFromNative(raw: unknown): FromNative | null {
    if (typeof raw !== 'object' || raw === null) return null;
    const m = raw as Record<string, unknown>;
    if (m.v !== SHELL_VERSION) return null;
    const str = (key: string): boolean => typeof m[key] === 'string' && (m[key] as string).length > 0;
    if (m.type === 'pushToken' && ['token', 'environment', 'payload_key', 'bundle_id', 'app_version'].every(str)) {
        return m as unknown as FromNative;
    }
    if (m.type === 'pushFailed') return { type: 'pushFailed', reason: typeof m.reason === 'string' ? m.reason : 'failed' };
    if (m.type === 'openPath' && isSafePath(m.path)) return { type: 'openPath', path: m.path };
    if (m.type === 'speech' && (m.kind === 'text' || m.kind === 'end' || m.kind === 'error')) {
        return {
            type: 'speech', kind: m.kind,
            text: typeof m.text === 'string' ? m.text : '', reason: typeof m.reason === 'string' ? m.reason : 'failed',
        };
    }
    return null;
}

function receive(raw: unknown): void {
    const message = parseFromNative(raw);
    if (!message) return;
    if (message.type === 'openPath') win().location.assign(message.path);
    for (const listener of [...listeners]) listener(message);
}

let bootedShell: object | null = null;

export function bootNativeShell(): boolean {
    if (!inNativeShell()) return false;
    const shell = win().carnivoreShell!;
    if (bootedShell === shell) return true;
    bootedShell = shell;
    shell.receive = receive;
    postToNative({ type: 'ready' });
    const sendTheme = (): void => {
        const id = activeGlobalThemeId();
        if (id) postToNative({ type: 'theme', id });
    };
    sendTheme();
    new MutationObserver(sendTheme).observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
    viewing = null;
    sendViewing();
    if (!viewingWired) {
        viewingWired = true;
        window.addEventListener(PRIMARY_BIND_EVENT, () => queueMicrotask(sendViewing));
        document.addEventListener('visibilitychange', sendViewing);
        window.addEventListener(WATCHED_EVENT, sendViewing);
    }
    return true;
}

let viewing: string | null = null;
let viewingWired = false;

function sendViewing(): void {
    const session = document.visibilityState === 'hidden' || !quietWatched.on ? '' : primaryTmuxName();
    if (session === viewing) return;
    viewing = session;
    postToNative({ type: 'viewing', session });
}
