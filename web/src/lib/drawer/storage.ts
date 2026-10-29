import { drawerEnv } from './env';

interface Migrator {
    readMigrating(key: string): string | null;
    writeMigrating(key: string, value: string): void;
}

function migrator(): Migrator | null {
    const m = (drawerEnv() as { BrowserStorageMigrate?: Migrator }).BrowserStorageMigrate;
    return m && typeof m.readMigrating === 'function' ? m : null;
}

export function readKey(key: string): string | null {
    const m = migrator();
    const store = (drawerEnv() as { localStorage?: Storage }).localStorage;
    if (m && store) store.getItem(key);
    if (m) return m.readMigrating(key);
    return store ? store.getItem(key) : null;
}

export function writeKey(key: string, value: string): void {
    const m = migrator();
    if (m) {
        m.writeMigrating(key, value);
        return;
    }
    const store = (drawerEnv() as { localStorage?: Storage }).localStorage;
    if (store) store.setItem(key, value);
}
