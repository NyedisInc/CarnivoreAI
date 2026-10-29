
export const ANIMATIONS_FIELD = 'animations';
const STORAGE_KEY = 'carnivore.animations';

interface Bridge {
    read(field: string, localReader: () => unknown): unknown;
    write(field: string, value: unknown, localWriter: () => void): Promise<unknown>;
}

function bridge(): Bridge | null {
    const found = (globalThis as { PreferenceBridge?: Bridge }).PreferenceBridge;
    return found && typeof found.read === 'function' ? found : null;
}

const SAVED = new Set(['committed', 'unchanged']);

function readLocal(): boolean {
    try {
        return localStorage.getItem(STORAGE_KEY) !== '0';
    } catch {
        return true;
    }
}

function writeLocal(on: boolean): void {
    try {
        localStorage.setItem(STORAGE_KEY, on ? '1' : '0');
    } catch {
    }
}

export function readAnimations(): boolean {
    return bridge()?.read(ANIMATIONS_FIELD, readLocal) !== false;
}

export async function saveAnimations(on: boolean): Promise<string | null> {
    const found = bridge();
    if (!found) return 'preferences are not available on this page';
    const result = (await found.write(ANIMATIONS_FIELD, on, () => writeLocal(on))) as
        { status?: string; detail?: string } | null;
    const status = result && typeof result.status === 'string' ? result.status : '';
    if (SAVED.has(status)) return null;
    return (result && result.detail) || status || 'the server did not answer';
}
