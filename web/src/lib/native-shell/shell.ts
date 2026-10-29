import { activeGlobalThemeId } from '../themes-page/global-theme';

export const SHELL_VERSION = 1;

export type ToNative =
    | { type: 'ready' }
    | { type: 'registerPush' }
    | { type: 'pushRegistered'; id: string }
    | { type: 'theme'; id: string };

export type FromNative =
    | { type: 'pushToken'; token: string; environment: string; payload_key: string; bundle_id: string; app_version: string }
    | { type: 'pushFailed'; reason: string }
    | { type: 'openPath'; path: string };

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
    return true;
}
