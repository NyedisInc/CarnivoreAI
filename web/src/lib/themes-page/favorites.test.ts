import { afterEach, describe, expect, test, vi } from 'vitest';
import { MAX_THEME_FAVORITES, THEME_FAVORITES_FIELD, themeFavorites, toIds } from './favorites.svelte';

function fakeBridge(shared: unknown) {
    let follower: ((value: unknown) => void) | null = null;
    const bridge = {
        read: vi.fn((_field: string, local: () => unknown) => shared ?? local()),
        write: vi.fn(async (_field: string, _value: unknown, local: () => void) => {
            local();
            return { status: 'committed' };
        }),
        follow: vi.fn((_field: string, apply: (value: unknown) => void) => {
            follower = apply;
            return () => {};
        }),
        push: (value: unknown) => follower?.(value),
    };
    (globalThis as { PreferenceBridge?: unknown }).PreferenceBridge = bridge;
    return bridge;
}

afterEach(() => {
    delete (globalThis as { PreferenceBridge?: unknown }).PreferenceBridge;
});

describe('the shared favorites list', () => {
    test('toIds keeps strings, drops repeats and anything that is not a list', () => {
        expect(toIds(['a', 7, 'a', '', 'b'])).toEqual(['a', 'b']);
        expect(toIds('a')).toEqual([]);
    });

    test('starts from the shared value, writes the whole list, and follows remote changes', () => {
        const bridge = fakeBridge(['matrix']);
        themeFavorites.start(null);
        expect(themeFavorites.ids).toEqual(['matrix']);

        themeFavorites.toggle('claude');
        expect(themeFavorites.ids).toEqual(['matrix', 'claude']);
        expect(bridge.write).toHaveBeenCalledWith(THEME_FAVORITES_FIELD, ['matrix', 'claude'], expect.any(Function));

        themeFavorites.toggle('matrix');
        expect(themeFavorites.ids).toEqual(['claude']);

        bridge.push(['nord']);
        expect(themeFavorites.has('nord')).toBe(true);
        expect(themeFavorites.has('claude')).toBe(false);
    });

    test('a star past the server cap is refused locally rather than sent', () => {
        const bridge = fakeBridge(null);
        themeFavorites.ids = Array.from({ length: MAX_THEME_FAVORITES }, (_, n) => `t${n}`);
        bridge.write.mockClear();
        expect(themeFavorites.toggle('one-more')).toBe(false);
        expect(bridge.write).not.toHaveBeenCalled();
        expect(themeFavorites.toggle('t0')).toBe(true);
    });
});
