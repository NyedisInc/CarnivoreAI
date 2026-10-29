
export const TOAST_MODE_FIELD = 'toast_mode';

export const TOAST_MODES = ['compact', 'detailed'] as const;

export type ToastMode = (typeof TOAST_MODES)[number];

interface Bridge {
    read(field: string, localReader: () => unknown): unknown;
    write(field: string, value: unknown, localWriter: () => void): Promise<unknown>;
    follow?(field: string, apply: (value: unknown) => void): () => void;
}

function bridge(): Bridge | null {
    const found = (globalThis as { PreferenceBridge?: Bridge }).PreferenceBridge;
    return found && typeof found.read === 'function' ? found : null;
}

const SAVED = new Set(['committed', 'unchanged']);

export function asMode(value: unknown): ToastMode {
    return value === 'detailed' ? 'detailed' : 'compact';
}

export function readToastMode(): ToastMode {
    return asMode(bridge()?.read(TOAST_MODE_FIELD, () => 'compact'));
}

export async function saveToastMode(mode: ToastMode): Promise<string | null> {
    const found = bridge();
    if (!found) return 'unavailable';
    const result = (await found.write(TOAST_MODE_FIELD, mode, () => {})) as
        { status?: string; detail?: string } | null;
    const status = result && typeof result.status === 'string' ? result.status : '';
    if (SAVED.has(status)) return null;
    return (result && result.detail) || status || 'the server did not answer';
}

export function followToastMode(apply: (mode: ToastMode) => void): () => void {
    const found = bridge();
    if (!found || typeof found.follow !== 'function') return () => {};
    return found.follow(TOAST_MODE_FIELD, (value) => apply(asMode(value)));
}
