
export const LAST_CALL_FIELD = 'warez_last_call';

interface Bridge {
    read(field: string, localReader: () => unknown): unknown;
    write(field: string, value: unknown, localWriter: () => void): Promise<unknown>;
}
interface Prefs {
    status?: () => string;
    HYDRATED?: string;
}

function bridge(): Bridge | null {
    const found = (globalThis as { PreferenceBridge?: Bridge }).PreferenceBridge;
    return found && typeof found.read === 'function' ? found : null;
}

export function prefsReady(): boolean {
    const prefs = (globalThis as { Preferences?: Prefs }).Preferences;
    return !!prefs && typeof prefs.status === 'function' && prefs.status() === (prefs.HYDRATED ?? 'hydrated');
}

export function prefsStatus(): string {
    const prefs = (globalThis as { Preferences?: Prefs }).Preferences;
    return prefs && typeof prefs.status === 'function' ? prefs.status() : '';
}

export async function hydratePrefs(): Promise<string> {
    const prefs = (globalThis as { Preferences?: { hydrate?: () => Promise<string> } }).Preferences;
    try {
        if (prefs && typeof prefs.hydrate === 'function') await prefs.hydrate();
    } catch (err) {
        console.warn('[elite] preference read failed', err);
    }
    return prefsStatus();
}

export async function save(field: string, value: unknown): Promise<void> {
    const found = bridge();
    if (!found) return;
    const result = (await found.write(field, value, () => {})) as { status?: string; detail?: string } | null;
    const status = result?.status ?? '';
    if (status !== 'committed' && status !== 'unchanged') console.warn('[elite] could not save', field, status, result?.detail ?? '');
}

export function readLastCall(): string | null {
    const v = prefsReady() ? bridge()?.read(LAST_CALL_FIELD, () => null) : null;
    return typeof v === 'string' && Number.isFinite(Date.parse(v)) ? v : null;
}

export async function stampLastCall(now: Date = new Date()): Promise<void> {
    if (!prefsReady()) return;
    await save(LAST_CALL_FIELD, now.toISOString());
}

export function dayText(iso: string): string {
    const d = new Date(iso);
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

/* first published */
export function newSince(items: readonly { id?: unknown; first_published_at?: unknown }[], since: string): Set<string> {
    const at = Date.parse(since);
    const out = new Set<string>();
    for (const i of items) {
        const t = typeof i.first_published_at === 'string' ? Date.parse(i.first_published_at) : NaN;
        if (Number.isFinite(t) && t > at) out.add(String(i.id));
    }
    return out;
}
