/** @vitest-environment jsdom */
import { mount, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { createI18n } from '../../../../client/js/i18n/runtime.js';

const { openElite, openNormal } = vi.hoisted(() => ({ openElite: vi.fn(() => true), openNormal: vi.fn(() => true) }));
vi.mock('../elite/elite-host', () => ({ openEliteScreen: openElite }));
vi.mock('../manager-frame/overlay-host', () => ({
    createOverlayHost: () => ({ open: openNormal, close: () => false, isHash: () => false }),
}));
vi.mock('./WarezScreen.svelte', () => ({ default: {} }));
vi.mock('../catalog/WarezScreen.svelte', () => ({ default: {} }));

const i18n = createI18n({ locale: 'en' }) as { t(key: string, params?: Record<string, unknown> | null): string };
const t = (key: string, params?: Record<string, unknown> | null) => i18n.t(key, params);

let status = 'hydrated';
let seen: unknown = null;
const writes: [string, unknown][] = [];

beforeEach(() => {
    status = 'hydrated';
    seen = null;
    writes.length = 0;
    openElite.mockClear();
    openNormal.mockClear();
    vi.stubGlobal('Preferences', {
        HYDRATED: 'hydrated',
        status: () => status,
        hydrate: vi.fn(async () => status),
    });
    vi.stubGlobal('PreferenceBridge', {
        read: (field: string) => (field === 'warez_elite_seen' ? seen : null),
        write: vi.fn(async (field: string, value: unknown) => {
            writes.push([field, value]);
            return { status: 'committed' };
        }),
    });
});
afterEach(() => vi.unstubAllGlobals());

describe('first Warez visit', () => {
    test('unset flag opens the BBS and writes the flag; set flag shows the normal page', async () => {
        const { openWarezScreen } = await import('../catalog/warez-host');
        expect(openWarezScreen()).toBe(true);
        expect(openElite).toHaveBeenCalledTimes(1);
        expect(openNormal).not.toHaveBeenCalled();
        expect(writes).toEqual([['warez_elite_seen', true]]);

        seen = true;
        writes.length = 0;
        openWarezScreen();
        expect(openElite).toHaveBeenCalledTimes(1);
        expect(openNormal).toHaveBeenCalledTimes(1);
        expect(writes).toEqual([]);
    });

    test('a failed read, and a targeted open, show the normal page', async () => {
        const { openWarezScreen } = await import('../catalog/warez-host');
        status = 'read_failed';
        openWarezScreen();
        status = 'hydrated';
        openWarezScreen({ kind: 'theme' });
        openWarezScreen({ home: true });
        expect(openElite).not.toHaveBeenCalled();
        expect(openNormal).toHaveBeenCalledTimes(3);
    });

    test('an unread block waits (nothing flashes), then decides', async () => {
        const { openWarezScreen } = await import('../catalog/warez-host');
        status = 'not_hydrated';
        (globalThis as typeof globalThis & { Preferences: { hydrate: () => Promise<string> } }).Preferences.hydrate = async () => { status = 'hydrated'; return status; };
        openWarezScreen();
        expect(openElite).not.toHaveBeenCalled();
        expect(openNormal).not.toHaveBeenCalled();
        await vi.waitFor(() => expect(openElite).toHaveBeenCalledTimes(1));
        expect(openNormal).not.toHaveBeenCalled();
        expect(writes).toEqual([['warez_elite_seen', true]]);
    });

    test('the title strip has no [ELITE ACCESS] button any more', async () => {
        const WarezActs = (await import('../catalog/WarezActs.svelte')).default;
        const target = document.createElement('div');
        document.body.appendChild(target);
        const handle = mount(WarezActs, { target, props: { refreshing: false, onRefresh: () => {}, onPublish: () => {}, t } });
        expect(target.querySelector('#warez-elite-open')).toBeNull();
        expect(target.textContent).not.toMatch(/elite access/i);
        unmount(handle);
    });
});
