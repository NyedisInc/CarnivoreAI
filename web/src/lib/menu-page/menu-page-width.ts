
export const WIDTH_FIELD = 'menu_page_width';
export const WIDTH_STORAGE_KEY = 'carnivore.menu-page.width';

interface WidthBridge {
    read?(field: string, fallback: () => number | null): unknown;
    write?(field: string, value: number | null, local: () => void): Promise<unknown>;
    follow?(field: string, apply: (value: unknown) => void): () => void;
}

interface WidthPreferences {
    retry?(field: string): Promise<{ status?: string; detail?: string }>;
}

export type WidthStorage = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>;

function bridge(): WidthBridge | undefined {
    return (globalThis as { PreferenceBridge?: WidthBridge }).PreferenceBridge;
}

function asWidth(raw: unknown): number | null {
    const n = typeof raw === 'string' ? Number(raw) : raw;
    return typeof n === 'number' && Number.isFinite(n) && n > 0 ? n : null;
}

function readLocal(storage: WidthStorage): number | null {
    try {
        const raw = storage.getItem(WIDTH_STORAGE_KEY);
        return raw == null ? null : asWidth(raw);
    } catch {
        return null;
    }
}

export function readDrawerWidth(storage: WidthStorage = window.localStorage): number | null {
    const b = bridge();
    return asWidth(b && typeof b.read === 'function' ? b.read(WIDTH_FIELD, () => readLocal(storage)) : readLocal(storage));
}

const listeners = new Set<(px: number | null) => void>();
let followed: WidthBridge | undefined;

function mirrorLocal(px: number | null, storage: WidthStorage): void {
    try {
        if (px == null) storage.removeItem(WIDTH_STORAGE_KEY);
        else storage.setItem(WIDTH_STORAGE_KEY, String(Math.round(px)));
    } catch {
    }
}

export function onWidthChange(listener: (px: number | null) => void): () => void {
    listeners.add(listener);
    const b = bridge();
    if (b && typeof b.follow === 'function' && followed !== b) {
        followed = b;
        b.follow(WIDTH_FIELD, (value) => {
            const px = asWidth(value);
            mirrorLocal(px, window.localStorage);
            listeners.forEach((l) => l(px));
        });
    }
    return () => void listeners.delete(listener);
}

async function checkSave(result: unknown): Promise<void> {
    const status = (result as { status?: string } | undefined)?.status;
    if (status === undefined || status === 'committed' || status === 'local_only') return;
    if (status === 'stale_revision') {
        const prefs = (globalThis as { Preferences?: WidthPreferences }).Preferences;
        const again = prefs && typeof prefs.retry === 'function' ? await prefs.retry(WIDTH_FIELD) : undefined;
        if (again?.status === 'committed') return;
        console.warn('menu page width: the replayed save was not committed:', again?.status ?? 'no retry available', again?.detail ?? '');
        return;
    }
    console.warn('menu page width: the save was not committed:', status);
}

export function writeDrawerWidth(px: number | null, storage: WidthStorage = window.localStorage): void {
    const value = px == null ? null : Math.round(px);
    const writeLocal = (): void => mirrorLocal(value, storage);
    const b = bridge();
    if (b && typeof b.write === 'function') {
        b.write(WIDTH_FIELD, value, writeLocal).then(checkSave).catch((err: unknown) => console.warn('menu page width: could not share it:', err));
    } else {
        writeLocal();
    }
}
