import { afterEach, describe, expect, test, vi } from 'vitest';

const waiting = vi.hoisted(() => [] as Array<() => void>);
vi.mock('../listing-push/boot', () => ({ whenListingPushBooted: (fn: () => void) => void waiting.push(fn) }));

import { SessionsData } from './sessions-data.svelte';

function build(): SessionsData {
    const api = { walk: () => Promise.resolve({ groups: [], peers: [], unavailable: [] }) };
    const readers = { records: () => Promise.resolve([]), counts: () => Promise.resolve({}) };
    return new SessionsData(api as never, readers as never, 'none', 'none');
}

afterEach(() => {
    waiting.length = 0;
    delete (globalThis as { ListingPush?: unknown }).ListingPush;
});

describe('SessionsData listing-push listener', () => {
    function installed(starts: number, stopAfter: boolean): number {
        const onChange = vi.fn(() => () => undefined);
        (globalThis as { ListingPush?: unknown }).ListingPush = { onChange };
        const data = build();
        for (let i = 0; i < starts; i += 1) data.start();
        if (stopAfter) data.stop();
        for (const fn of waiting.splice(0)) fn();
        const calls = onChange.mock.calls.length;
        data.stop();
        return calls;
    }

    test('a boot that lands after stop() installs fewer listeners than a live start, and a superseded start adds none', () => {
        const single = installed(1, false);
        expect(single).toBeGreaterThan(0);
        expect(installed(2, false)).toBe(single);
        expect(installed(2, true)).toBe(0);
    });
});
