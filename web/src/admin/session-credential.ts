
export interface SessionCredentialStorage {
    getItem(key: string): string | null;
    setItem(key: string, value: string): void;
    removeItem(key: string): void;
}

function safeGet(store: SessionCredentialStorage, key: string): string | null {
    try {
        const value = store.getItem(key);
        return typeof value === 'string' ? value : null;
    } catch (error) {
        return null;
    }
}

function safeSet(store: SessionCredentialStorage, key: string, value: string): void {
    try {
        store.setItem(key, value);
    } catch (error) {
    }
}

function safeRemove(store: SessionCredentialStorage, key: string): void {
    try {
        store.removeItem(key);
    } catch (error) {
    }
}

export function readSessionCredential(
    store: SessionCredentialStorage,
    key: string,
    legacyKey: string,
): string {
    const current = safeGet(store, key);
    if (current !== null) return current;
    const legacy = safeGet(store, legacyKey);
    if (legacy === null) return '';
    safeSet(store, key, legacy);
    safeRemove(store, legacyKey);
    return legacy;
}

export function writeSessionCredential(
    store: SessionCredentialStorage,
    key: string,
    legacyKey: string,
    value: string,
): void {
    safeSet(store, key, value);
    safeRemove(store, legacyKey);
}

export function clearSessionCredential(
    store: SessionCredentialStorage,
    key: string,
    legacyKey: string,
): void {
    safeRemove(store, key);
    safeRemove(store, legacyKey);
}
