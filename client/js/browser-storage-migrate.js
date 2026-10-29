
import { BROWSER_KEY_PREFIX, LEGACY_BROWSER_KEY_PREFIXES } from './product-identity.js';

function legacyKeyFor(key) {
    if (typeof key !== 'string' || !key.startsWith(BROWSER_KEY_PREFIX)) return null;
    const suffix = key.slice(BROWSER_KEY_PREFIX.length);
    for (const legacyPrefix of LEGACY_BROWSER_KEY_PREFIXES) {
        return legacyPrefix + suffix;
    }
    return null;
}

function safeGet(store, key) {
    try {
        const value = store.getItem(key);
        return typeof value === 'string' ? value : null;
    } catch (err) {
        return null;
    }
}

function safeSet(store, key, value) {
    try {
        store.setItem(key, value);
    } catch (err) {
    }
}

function safeRemove(store, key) {
    try {
        store.removeItem(key);
    } catch (err) {
    }
}

export function readMigrating(key, storage) {
    const store = storage || globalThis.localStorage;
    if (!store || typeof store.getItem !== 'function') return null;
    const current = safeGet(store, key);
    if (current !== null) return current;
    const legacyKey = legacyKeyFor(key);
    if (!legacyKey) return null;
    const legacy = safeGet(store, legacyKey);
    if (legacy === null) return null;
    safeSet(store, key, legacy);
    return legacy;
}

export function writeMigrating(key, value, storage) {
    const store = storage || globalThis.localStorage;
    if (!store || typeof store.setItem !== 'function') return;
    safeSet(store, key, value);
    const legacyKey = legacyKeyFor(key);
    if (legacyKey) safeSet(store, legacyKey, value);
}

export function readMigratingCredential(key, storage) {
    const store = storage || globalThis.localStorage;
    if (!store || typeof store.getItem !== 'function') return null;
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

export function writeMigratingCredential(key, value, storage) {
    const store = storage || globalThis.localStorage;
    if (!store || typeof store.setItem !== 'function') return;
    safeSet(store, key, value);
    const legacyKey = legacyKeyFor(key);
    if (legacyKey) safeRemove(store, legacyKey);
}

const api = {
    readMigrating,
    writeMigrating,
    readMigratingCredential,
    writeMigratingCredential,
};

globalThis.BrowserStorageMigrate = api;
