
import { BROWSER_KEY_PREFIX, LEGACY_BROWSER_KEY_PREFIXES } from './product-identity';

export interface MigratableStorage {
    getItem(key: string): string | null;
    setItem(key: string, value: string): void;
    removeItem(key: string): void;
}

function legacyKeyFor(key: string): string | null {
    if (typeof key !== 'string' || !key.startsWith(BROWSER_KEY_PREFIX)) return null;
    const suffix = key.slice(BROWSER_KEY_PREFIX.length);
    for (const legacyPrefix of LEGACY_BROWSER_KEY_PREFIXES) {
        return legacyPrefix + suffix;
    }
    return null;
}

function safeGet(store: MigratableStorage, key: string): string | null {
    try {
        const value = store.getItem(key);
        return typeof value === 'string' ? value : null;
    } catch (err) {
        return null;
    }
}

function safeSet(store: MigratableStorage, key: string, value: string): void {
    try {
        store.setItem(key, value);
    } catch (err) {
    }
}

function safeRemove(store: MigratableStorage, key: string): void {
    try {
        store.removeItem(key);
    } catch (err) {
    }
}

function resolve(storage: MigratableStorage | undefined): MigratableStorage | null {
    if (storage) return storage;
    try {
        return (globalThis as { localStorage?: MigratableStorage }).localStorage || null;
    } catch (err) {
        return null;
    }
}

export function readMigrating(key: string, storage?: MigratableStorage): string | null {
    const store = resolve(storage);
    if (!store) return null;
    const current = safeGet(store, key);
    if (current !== null) return current;
    const legacyKey = legacyKeyFor(key);
    if (!legacyKey) return null;
    const legacy = safeGet(store, legacyKey);
    if (legacy === null) return null;
    safeSet(store, key, legacy);
    return legacy;
}

export function writeMigrating(
    key: string,
    value: string,
    storage?: MigratableStorage,
): void {
    const store = resolve(storage);
    if (!store) return;
    safeSet(store, key, value);
    const legacyKey = legacyKeyFor(key);
    if (legacyKey) safeSet(store, legacyKey, value);
}

export function readMigratingCredential(
    key: string,
    storage?: MigratableStorage,
): string | null {
    const store = resolve(storage);
    if (!store) return null;
    const current = safeGet(store, key);
    if (current !== null) return current;
    const legacyKey = legacyKeyFor(key);
    if (!legacyKey) return null;
    const legacy = safeGet(store, legacyKey);
    if (legacy === null) return null;
    safeSet(store, key, legacy);
    safeRemove(store, legacyKey);
    return legacy;
}

export function writeMigratingCredential(
    key: string,
    value: string,
    storage?: MigratableStorage,
): void {
    const store = resolve(storage);
    if (!store) return;
    safeSet(store, key, value);
    const legacyKey = legacyKeyFor(key);
    if (legacyKey) safeRemove(store, legacyKey);
}
