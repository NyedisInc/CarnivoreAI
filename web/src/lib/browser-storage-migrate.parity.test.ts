import { fileURLToPath } from 'node:url';

import { describe, expect, test } from 'vitest';

import {
    readMigrating,
    writeMigrating,
    readMigratingCredential,
    writeMigratingCredential,
    type MigratableStorage,
} from './browser-storage-migrate';

const LEGACY_PATH = fileURLToPath(
    new URL('../../../client/js/browser-storage-migrate.js', import.meta.url),
);

interface LegacyApi {
    readMigrating(key: string, storage?: MigratableStorage): string | null;
    writeMigrating(key: string, value: string, storage?: MigratableStorage): void;
    readMigratingCredential(key: string, storage?: MigratableStorage): string | null;
    writeMigratingCredential(
        key: string,
        value: string,
        storage?: MigratableStorage,
    ): void;
}

async function legacy(): Promise<LegacyApi> {
    return (await import(/* @vite-ignore */ LEGACY_PATH)) as unknown as LegacyApi;
}

class FakeStorage implements MigratableStorage {
    private map = new Map<string, string>();

    getItem(key: string): string | null {
        return this.map.has(key) ? (this.map.get(key) as string) : null;
    }

    setItem(key: string, value: string): void {
        this.map.set(key, String(value));
    }

    removeItem(key: string): void {
        this.map.delete(key);
    }

    snapshot(): Record<string, string> {
        const out: Record<string, string> = {};
        for (const key of [...this.map.keys()].sort()) out[key] = this.map.get(key) as string;
        return out;
    }
}

describe('browser-storage-migrate: byte-identical to the legacy client/js module', () => {
    test('the legacy file loads as a real ES module', async () => {
        const api = await legacy();
        expect(typeof api.readMigrating).toBe('function');
        expect(typeof api.writeMigrating).toBe('function');
        expect(typeof api.readMigratingCredential).toBe('function');
        expect(typeof api.writeMigratingCredential).toBe('function');
    });

    test('readMigrating: new key present short-circuits, legacy untouched', async () => {
        const api = await legacy();
        const mine = new FakeStorage();
        const theirs = new FakeStorage();
        for (const store of [mine, theirs]) {
            store.setItem('carnivore.theme', 'ascii-argent');
            store.setItem('cloude.theme', 'stale-legacy-value');
        }
        const mineValue = readMigrating('carnivore.theme', mine);
        const theirsValue = api.readMigrating('carnivore.theme', theirs);
        expect(mineValue).toBe('ascii-argent');
        expect(theirsValue).toBe(mineValue);
        expect(mine.snapshot()).toEqual(theirs.snapshot());
    });

    test('readMigrating: legacy-only value is copied forward, legacy kept', async () => {
        const api = await legacy();
        const mine = new FakeStorage();
        const theirs = new FakeStorage();
        for (const store of [mine, theirs]) store.setItem('cloude.theme', 'ascii-nostromo');

        const mineValue = readMigrating('carnivore.theme', mine);
        const theirsValue = api.readMigrating('carnivore.theme', theirs);

        expect(mineValue).toBe('ascii-nostromo');
        expect(theirsValue).toBe(mineValue);
        expect(mine.snapshot()).toEqual(theirs.snapshot());
        expect(mine.getItem('cloude.theme')).toBe('ascii-nostromo');
        expect(mine.getItem('carnivore.theme')).toBe('ascii-nostromo');
    });

    test('readMigrating: neither key present answers null on both sides', async () => {
        const api = await legacy();
        const mine = new FakeStorage();
        const theirs = new FakeStorage();
        expect(readMigrating('carnivore.session.sidebar.density', mine)).toBeNull();
        expect(api.readMigrating('carnivore.session.sidebar.density', theirs)).toBeNull();
        expect(mine.snapshot()).toEqual(theirs.snapshot());
    });

    test('readMigrating: a key outside the carnivore.* namespace has no legacy fallback', async () => {
        const api = await legacy();
        const mine = new FakeStorage();
        const theirs = new FakeStorage();
        for (const store of [mine, theirs]) store.setItem('cloude_provider_last_model', 'sonnet');
        expect(readMigrating('carnivore_provider_last_model', mine)).toBeNull();
        expect(api.readMigrating('carnivore_provider_last_model', theirs)).toBeNull();
        expect(mine.snapshot()).toEqual(theirs.snapshot());
    });

    test('writeMigrating: lands on both the new key and the legacy twin', async () => {
        const api = await legacy();
        const mine = new FakeStorage();
        const theirs = new FakeStorage();
        writeMigrating('carnivore.theme', 'oblivion', mine);
        api.writeMigrating('carnivore.theme', 'oblivion', theirs);
        expect(mine.snapshot()).toEqual(theirs.snapshot());
        expect(mine.getItem('carnivore.theme')).toBe('oblivion');
        expect(mine.getItem('cloude.theme')).toBe('oblivion');
    });

    test('readMigratingCredential: new key present short-circuits, legacy untouched', async () => {
        const api = await legacy();
        const mine = new FakeStorage();
        const theirs = new FakeStorage();
        for (const store of [mine, theirs]) {
            store.setItem('carnivore.admin.access_token', 'fresh-token');
            store.setItem('cloude.admin.access_token', 'stale-token');
        }
        const mineValue = readMigratingCredential('carnivore.admin.access_token', mine);
        const theirsValue = api.readMigratingCredential('carnivore.admin.access_token', theirs);
        expect(mineValue).toBe('fresh-token');
        expect(theirsValue).toBe(mineValue);
        expect(mine.snapshot()).toEqual(theirs.snapshot());
        expect(mine.getItem('cloude.admin.access_token')).toBe('stale-token');
    });

    test('readMigratingCredential: a legacy-only value is MOVED, never left resting under both keys', async () => {
        const api = await legacy();
        const mine = new FakeStorage();
        const theirs = new FakeStorage();
        for (const store of [mine, theirs]) store.setItem('cloude.admin.access_token', 'legacy-token');

        const mineValue = readMigratingCredential('carnivore.admin.access_token', mine);
        const theirsValue = api.readMigratingCredential('carnivore.admin.access_token', theirs);

        expect(mineValue).toBe('legacy-token');
        expect(theirsValue).toBe(mineValue);
        expect(mine.snapshot()).toEqual(theirs.snapshot());
        expect(mine.getItem('carnivore.admin.access_token')).toBe('legacy-token');
        expect(mine.getItem('cloude.admin.access_token')).toBeNull();
        expect(mine.snapshot()).toEqual({ 'carnivore.admin.access_token': 'legacy-token' });
    });

    test('writeMigratingCredential: lands on the new key only, legacy name never re-minted', async () => {
        const api = await legacy();
        const mine = new FakeStorage();
        const theirs = new FakeStorage();
        writeMigratingCredential('carnivore.admin.access_token', 'brand-new-token', mine);
        api.writeMigratingCredential('carnivore.admin.access_token', 'brand-new-token', theirs);
        expect(mine.snapshot()).toEqual(theirs.snapshot());
        expect(mine.snapshot()).toEqual({ 'carnivore.admin.access_token': 'brand-new-token' });
        expect(mine.getItem('cloude.admin.access_token')).toBeNull();
    });

    test('writeMigratingCredential also erases a legacy leftover it never read', async () => {
        const api = await legacy();
        const mine = new FakeStorage();
        const theirs = new FakeStorage();
        for (const store of [mine, theirs]) {
            store.setItem('cloude.admin.access_token', 'stale-previous-session-token');
        }
        writeMigratingCredential('carnivore.admin.access_token', 'fresh-login-token', mine);
        api.writeMigratingCredential('carnivore.admin.access_token', 'fresh-login-token', theirs);
        expect(mine.snapshot()).toEqual(theirs.snapshot());
        expect(mine.snapshot()).toEqual({ 'carnivore.admin.access_token': 'fresh-login-token' });
    });

    test('a credential read never leaves a value resting under two keys at once, across a whole sequence', async () => {
        const api = await legacy();
        const mine = new FakeStorage();
        const theirs = new FakeStorage();
        for (const store of [mine, theirs]) store.setItem('cloude.admin.access_token', 'first-login-token');

        for (let i = 0; i < 2; i++) {
            readMigratingCredential('carnivore.admin.access_token', mine);
            api.readMigratingCredential('carnivore.admin.access_token', theirs);
            const mineKeys = Object.keys(mine.snapshot());
            expect(mineKeys.length, `pass ${i}`).toBe(1);
            expect(mineKeys[0], `pass ${i}`).toBe('carnivore.admin.access_token');
        }
        expect(mine.snapshot()).toEqual(theirs.snapshot());
    });

    test('NEGATIVE CONTROL: the comparison can actually fail', async () => {
        // disagree.
        const api = await legacy();
        const mine = new FakeStorage();
        const theirs = new FakeStorage();
        mine.setItem('cloude.theme', 'ascii-argent');
        theirs.setItem('cloude.theme', 'ascii-nostromo');
        const mineValue = readMigrating('carnivore.theme', mine);
        const theirsValue = api.readMigrating('carnivore.theme', theirs);
        expect(mineValue).not.toBe(theirsValue);
    });
});
