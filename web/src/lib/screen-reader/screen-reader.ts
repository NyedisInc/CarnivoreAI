
export const SCREEN_READER_FIELD = 'terminal_screen_reader';

export const SCREEN_READER_MODES = ['auto', 'on', 'off'] as const;

export type ScreenReaderMode = (typeof SCREEN_READER_MODES)[number];

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

export function asMode(value: unknown): ScreenReaderMode {
    return value === 'on' || value === 'off' ? value : 'auto';
}

export function readScreenReaderMode(): ScreenReaderMode {
    return asMode(bridge()?.read(SCREEN_READER_FIELD, () => 'auto'));
}

export async function saveScreenReaderMode(mode: ScreenReaderMode): Promise<string | null> {
    const found = bridge();
    if (!found) return 'unavailable';
    const result = (await found.write(SCREEN_READER_FIELD, mode, () => {})) as { status?: string; detail?: string } | null;
    const status = result && typeof result.status === 'string' ? result.status : '';
    if (SAVED.has(status)) return null;
    return (result && result.detail) || status || 'the server did not answer';
}

export function followScreenReaderMode(apply: (mode: ScreenReaderMode) => void): () => void {
    const found = bridge();
    if (!found || typeof found.follow !== 'function') return () => {};
    return found.follow(SCREEN_READER_FIELD, (value) => apply(asMode(value)));
}
