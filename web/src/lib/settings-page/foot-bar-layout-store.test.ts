import { afterEach, expect, test } from 'vitest';
import { footBarLayout, sanitize } from './foot-bar-layout-store.svelte';

afterEach(() => {
    delete (globalThis as { PreferenceBridge?: unknown }).PreferenceBridge;
    footBarLayout.value = {};
});

test('effective() defaults to "a" for both halves', () => {
    expect(footBarLayout.effective('collapsed')).toBe('a');
    expect(footBarLayout.effective('open')).toBe('a');
});

test('sanitize() drops an unknown option and keeps only collapsed/open', () => {
    expect(sanitize({ collapsed: 'b', open: 'z', bogus: 1 })).toEqual({ collapsed: 'b' });
    expect(sanitize(null)).toEqual({});
});

test('set() always writes both halves explicitly, never a sparse object', () => {
    const written: unknown[] = [];
    (globalThis as { PreferenceBridge?: unknown }).PreferenceBridge = {
        read: () => null,
        write: (_field: string, value: unknown) => { written.push(value); return Promise.resolve(value); },
        follow: () => () => {},
    };
    footBarLayout.set('collapsed', 'b');
    expect(footBarLayout.effective('collapsed')).toBe('b');
    expect(footBarLayout.effective('open')).toBe('a'); // untouched, still the default
    expect(written).toEqual([{ collapsed: 'b', open: 'a' }]);

    footBarLayout.set('open', 'c');
    expect(written[1]).toEqual({ collapsed: 'b', open: 'c' });
});
