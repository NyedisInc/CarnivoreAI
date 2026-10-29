
export const CACHE_VERSION = 1;

const DB_NAME = 'carnivore-data-cache';
const STORE_NAME = 'entries';

const TOKEN_KEY = 'claude_tunnel_token';

export const WRITE_INTERVAL_MS = 5000;

export const MAX_ENTRY_BYTES = 2_000_000;

interface Entry {
    v: number;
    savedAt: number;
    json: string;
}

export interface CacheBackend {
    get(key: string): Promise<unknown>;
    put(key: string, value: unknown): Promise<void>;
    clear(): Promise<void>;
}

function settle<T>(request: IDBRequest<T>): Promise<T> {
    return new Promise((resolve, reject) => {
        request.onsuccess = () => resolve(request.result);
        request.onerror = () => reject(request.error);
    });
}

export function indexedDbBackend(): CacheBackend {
    let opened: Promise<IDBDatabase> | null = null;
    const open = (): Promise<IDBDatabase> => {
        if (!opened) {
            opened = new Promise<IDBDatabase>((resolve, reject) => {
                const request = globalThis.indexedDB.open(DB_NAME, 1);
                request.onupgradeneeded = () => request.result.createObjectStore(STORE_NAME);
                request.onsuccess = () => resolve(request.result);
                request.onerror = () => reject(request.error);
                request.onblocked = () => reject(new Error('indexedDB open blocked'));
            });
        }
        return opened;
    };
    const store = async (mode: IDBTransactionMode): Promise<IDBObjectStore> =>
        (await open()).transaction(STORE_NAME, mode).objectStore(STORE_NAME);
    return {
        get: async (key) => settle((await store('readonly')).get(key)),
        put: async (key, value) => { await settle((await store('readwrite')).put(value, key)); },
        clear: async () => { await settle((await store('readwrite')).clear()); },
    };
}

let backend: CacheBackend | null = null;

function active(): CacheBackend | null {
    if (backend) return backend;
    if (typeof globalThis.indexedDB === 'undefined') return null;
    backend = indexedDbBackend();
    return backend;
}

export function setCacheBackend(next: CacheBackend | null): void {
    backend = next;
}

function identity(): string | null {
    try {
        const token = globalThis.localStorage?.getItem(TOKEN_KEY);
        if (!token) return null;
        const body = token.split('.')[1];
        if (!body) return null;
        const json = atob(body.replace(/-/g, '+').replace(/_/g, '/'));
        const sub = (JSON.parse(json) as { sub?: unknown }).sub;
        return typeof sub === 'string' && sub ? sub : null;
    } catch {
        return null;
    }
}

export function cacheScope(): string | null {
    const who = identity();
    const origin = globalThis.location?.origin;
    return who && origin ? `${origin}|${who}` : null;
}

export async function readCached<T>(name: string): Promise<T | null> {
    const scope = cacheScope();
    const engine = active();
    if (!scope || !engine) return null;
    try {
        const entry = (await engine.get(`${scope}|${name}`)) as Entry | undefined;
        return entry && entry.v === CACHE_VERSION && typeof entry.json === 'string' ? (JSON.parse(entry.json) as T) : null;
    } catch (err) {
        console.warn('data-cache: read failed, working without it:', (err as Error)?.message);
        return null;
    }
}

export async function writeCached<T>(name: string, data: T): Promise<boolean> {
    const scope = cacheScope();
    const engine = active();
    if (!scope || !engine) return false;
    try {
        const json = JSON.stringify(data);
        if (json.length > MAX_ENTRY_BYTES) return false;
        const entry: Entry = { v: CACHE_VERSION, savedAt: Date.now(), json };
        await engine.put(`${scope}|${name}`, entry);
        return true;
    } catch (err) {
        console.warn('data-cache: write failed, dropped:', (err as Error)?.message);
        return false;
    }
}

export async function clearDataCache(): Promise<void> {
    const engine = active();
    if (!engine) return;
    try {
        await engine.clear();
    } catch (err) {
        console.warn('data-cache: clear failed:', (err as Error)?.message);
    }
}

export interface ThrottledWriter {
    schedule(): void;
    flush(): void;
}

export function throttledWriter<T>(
    name: string,
    build: () => T | null,
    intervalMs: number = WRITE_INTERVAL_MS,
    timers: { set(fn: () => void, ms: number): unknown; clear(h: unknown): void } = {
        set: (fn, ms) => setTimeout(fn, ms),
        clear: (h) => clearTimeout(h as ReturnType<typeof setTimeout>),
    },
): ThrottledWriter {
    let timer: unknown = null;
    let pending = false;
    let lastAt = Number.NEGATIVE_INFINITY;
    const save = (): void => {
        if (timer !== null) { timers.clear(timer); timer = null; }
        if (!pending) return;
        pending = false;
        lastAt = Date.now();
        const value = build();
        if (value !== null) void writeCached(name, value);
    };
    const writer: ThrottledWriter = {
        schedule() {
            pending = true;
            if (timer !== null) return;
            const wait = Math.max(0, lastAt + intervalMs - Date.now());
            timer = timers.set(() => { timer = null; save(); }, wait);
        },
        flush: save,
    };
    writers.add(writer);
    bindLifecycle();
    return writer;
}

const writers = new Set<ThrottledWriter>();
let lifecycleBound = false;

function bindLifecycle(): void {
    if (lifecycleBound || typeof globalThis.addEventListener !== 'function') return;
    lifecycleBound = true;
    globalThis.addEventListener('pagehide', () => { for (const w of writers) w.flush(); });
    globalThis.addEventListener('logged-out', () => { void clearDataCache(); });
}
