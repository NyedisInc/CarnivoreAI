/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';

const pack = vi.hoisted(() => ({ data: null as null | { machines: unknown[] }, refresh: vi.fn() }));
vi.mock('../pack-machines/pack-machines-store.svelte', () => ({ packMachines: pack }));

import './menus/all';
import { itemMenu } from './registry';
import { ctxOf } from './row-test-env';

async function openSendTo(): Promise<number> {
    let rebuilt = 0;
    const built = itemMenu('session', ctxOf({ name: 'cloude_x', sessionUuid: 'su-x', status: 'idle' }), {
        close: () => {}, glyph: () => '', refresh: () => { rebuilt += 1; },
    });
    const sendTo = built?.nodes.find((n) => n.id === 'send-to');
    expect(sendTo, 'a live session row offers send to').toBeTruthy();
    const kids = sendTo!.children;
    if (typeof kids === 'function') (kids as () => unknown)();
    for (let i = 0; i < 5; i += 1) await Promise.resolve();
    return rebuilt;
}

afterEach(() => {
    pack.data = null;
    pack.refresh.mockReset();
});

describe('send to reads the Pack roster once per open', () => {
    test('a first read that fails does not rebuild the menu (no read loop)', async () => {
        pack.refresh.mockResolvedValue(undefined);
        expect(await openSendTo()).toBe(0);
        expect(pack.refresh).toHaveBeenCalledTimes(1);
    });

    test('a first read that lands rebuilds the open menu once', async () => {
        pack.refresh.mockImplementation(async () => { pack.data = { machines: [] }; });
        expect(await openSendTo()).toBe(1);
    });
});
