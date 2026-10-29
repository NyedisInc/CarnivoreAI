import { afterEach, describe, expect, test } from 'vitest';
import { rowIcons, sanitize as sanitizeRowIcons } from './row-icons-store.svelte';
import { footBarItems, sanitize as sanitizeFootBarItems } from './foot-bar-items-store.svelte';

afterEach(() => {
    delete (globalThis as { PreferenceBridge?: unknown }).PreferenceBridge;
    rowIcons.value = {};
    footBarItems.value = {};
});

describe('row icons', () => {
    test('effective() falls back per density: compact off, cozy/detailed on', () => {
        expect(rowIcons.effective('compact', 'agents')).toBe(false);
        expect(rowIcons.effective('cozy', 'shells')).toBe(true);
        expect(rowIcons.effective('detailed', 'timers')).toBe(true);
    });

    test('sanitize() drops non-boolean and unknown entries, keeps the rest sparse', () => {
        expect(sanitizeRowIcons({ compact: { agents: true, bogus: 1 }, nonsense: 'x' })).toEqual({
            compact: { agents: true },
        });
        expect(sanitizeRowIcons(null)).toEqual({});
    });

    test('set() merges one cell without disturbing the others', () => {
        const written: unknown[] = [];
        (globalThis as { PreferenceBridge?: unknown }).PreferenceBridge = {
            read: () => null,
            write: (_field: string, value: unknown) => { written.push(value); return Promise.resolve(value); },
            follow: () => () => {},
        };
        rowIcons.set('compact', 'agents', true);
        expect(rowIcons.effective('compact', 'agents')).toBe(true);
        expect(rowIcons.effective('compact', 'shells')).toBe(false); // untouched, still the default
        expect(written).toEqual([{ compact: { agents: true } }]);

        rowIcons.set('cozy', 'timers', false);
        expect(written[1]).toEqual({ compact: { agents: true }, cozy: { timers: false } });
    });

    test('a refused write reloads the stored value, so the grid stops showing a change the server never took (u150-07)', async () => {
        let stored: unknown = { cozy: { timers: false } };
        (globalThis as { PreferenceBridge?: unknown }).PreferenceBridge = {
            read: () => stored,
            write: () => Promise.resolve({ status: 'refused', detail: 'preferences have not been read yet' }),
            follow: () => () => {},
        };
        rowIcons.reload();
        rowIcons.set('compact', 'agents', true);
        expect(rowIcons.effective('compact', 'agents')).toBe(true);
        await new Promise((r) => setTimeout(r, 0));
        expect(rowIcons.effective('compact', 'agents')).toBe(false);
        expect(rowIcons.effective('cozy', 'timers')).toBe(false);
        stored = null;
    });
});

describe('foot bar items', () => {
    test('effective() defaults to on for everything', () => {
        expect(footBarItems.effective('model')).toBe(true);
        expect(footBarItems.effective('window_5h')).toBe(true);
    });

    test('sanitize() drops unknown keys', () => {
        expect(sanitizeFootBarItems({ model: false, bogus: 1 })).toEqual({ model: false });
    });

    test('set() writes only the changed item, sparse', () => {
        const written: unknown[] = [];
        (globalThis as { PreferenceBridge?: unknown }).PreferenceBridge = {
            read: () => null,
            write: (_field: string, value: unknown) => { written.push(value); return Promise.resolve(value); },
            follow: () => () => {},
        };
        footBarItems.set('effort', false);
        expect(footBarItems.effective('effort')).toBe(false);
        expect(footBarItems.effective('context')).toBe(true);
        expect(written).toEqual([{ effort: false }]);
    });

    test('a refused write reloads the stored value, so the checkbox stops showing a change the server never took (u150-07)', async () => {
        (globalThis as { PreferenceBridge?: unknown }).PreferenceBridge = {
            read: () => ({ model: false }),
            write: () => Promise.resolve({ status: 'refused', detail: 'preferences have not been read yet' }),
            follow: () => () => {},
        };
        footBarItems.reload();
        footBarItems.set('effort', false);
        expect(footBarItems.effective('effort')).toBe(false);
        await new Promise((r) => setTimeout(r, 0));
        expect(footBarItems.effective('effort')).toBe(true);
        expect(footBarItems.effective('model')).toBe(false);
        (globalThis as { PreferenceBridge?: unknown }).PreferenceBridge = undefined;
    });
});
