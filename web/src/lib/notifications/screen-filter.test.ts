import { afterEach, describe, expect, test } from 'vitest';

import { installNotifyScreen, resetNotifyScreenForTests, ScreenFilter } from './screen-filter';

const TYPES = [
    { id: 'session.permission', family: 'needs_you' },
    { id: 'approval.agent_action', family: 'needs_you' },
    { id: 'session.finished', family: 'sessions' },
    { id: 'session.posted', family: 'sessions' },
];

function fetcherOf(screen: Record<string, boolean>, fail = false) {
    return (async (path: string) => {
        if (path === '/notifications/types') return { types: TYPES };
        if (fail) throw new Error('down');
        return { screen: Object.fromEntries(Object.entries(screen).map(([k, v]) => [k, { value: v, source: 'global', locked: false }])) };
    }) as never;
}

afterEach(resetNotifyScreenForTests);

describe('ScreenFilter.shows', () => {
    test('an unticked type is hidden and a ticked type is shown', async () => {
        const f = new ScreenFilter(fetcherOf({ 'session.finished': false, 'session.posted': true }));
        await f.refresh();
        expect(f.shows({ notify_type: 'session.finished' })).toBe(false);
        expect(f.shows({ notify_type: 'session.posted' })).toBe(true);
    });

    test('needs-you types hide when their screen cell is unticked and show when ticked', async () => {
        const f = new ScreenFilter(fetcherOf({ 'session.permission': false, 'approval.agent_action': false }));
        await f.refresh();
        expect(f.shows({ notify_type: 'session.permission' })).toBe(false);
        expect(f.shows({ notify_type: 'approval.agent_action' })).toBe(false);
    });

    test('a toast with no notify_type, an unknown type and a null toast are shown', async () => {
        const f = new ScreenFilter(fetcherOf({ 'session.finished': false }));
        await f.refresh();
        expect(f.shows({})).toBe(true);
        expect(f.shows({ notify_type: '' })).toBe(true);
        expect(f.shows({ notify_type: 'future.type' })).toBe(true);
        expect(f.shows(null)).toBe(true);
        expect(f.shows({ notify_type: 7 })).toBe(true);
    });

    test('before the first read, and after any failed read, everything shows', async () => {
        const f = new ScreenFilter(fetcherOf({ 'session.finished': false }, true));
        expect(f.shows({ notify_type: 'session.finished' })).toBe(true);
        await f.refresh();
        expect(f.shows({ notify_type: 'session.finished' })).toBe(true);
    });

    test('a read that succeeds after a failure starts hiding again, and the registry is read once', async () => {
        let mode: 'ok' | 'fail' = 'ok';
        let typeReads = 0;
        const fetcher = (async (path: string) => {
            if (path === '/notifications/types') { typeReads += 1; return { types: TYPES }; }
            if (mode === 'fail') throw new Error('down');
            return { screen: { 'session.finished': { value: false } } };
        }) as never;
        const f = new ScreenFilter(fetcher);
        await f.refresh();
        expect(f.shows({ notify_type: 'session.finished' })).toBe(false);
        mode = 'fail';
        await f.refresh();
        expect(f.shows({ notify_type: 'session.finished' })).toBe(true);
        mode = 'ok';
        await f.refresh();
        expect(f.shows({ notify_type: 'session.finished' })).toBe(false);
        expect(typeReads).toBe(1);
    });
});

describe('installNotifyScreen', () => {
    test('publishes window.NotifyScreen.shows and is idempotent', async () => {
        const first = installNotifyScreen(fetcherOf({ 'session.finished': false }));
        await first.refresh();
        const host = globalThis as unknown as { NotifyScreen: { shows(t: unknown): boolean } };
        expect(host.NotifyScreen.shows({ notify_type: 'session.finished' })).toBe(false);
        expect(installNotifyScreen()).toBe(first);
    });
});
