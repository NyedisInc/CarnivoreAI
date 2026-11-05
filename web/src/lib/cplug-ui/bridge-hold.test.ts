/** @vitest-environment jsdom */
import { describe, expect, test, vi } from 'vitest';
import { createBridge } from './bridge';
import { createFrameTopics } from './frame-topics';

const NONCE = 'n'.repeat(32);

function rig() {
    const posted: Record<string, unknown>[] = [];
    const win = { postMessage: (m: unknown) => posted.push(m as Record<string, unknown>) };
    const calls: string[] = [];
    const callRoute = vi.fn(async (_route: string, payload: unknown) => { calls.push(String((payload as { n: number }).n)); return { echoed: payload }; });
    let visible = false;
    const bridge = createBridge({ nonce: NONCE, frame: () => win, declared: { routes: ['feed'], tools: [] }, callRoute, viewport: () => ({ w: 1, h: 1 }), visible: () => visible });
    bridge.init();
    posted.length = 0;
    const call = (n: number) => bridge.handle({ source: win, data: { nonce: NONCE, verb: 'route.call', id: `c${n}`, route: 'feed', payload: { n } } });
    return { bridge, posted, callRoute, calls, call, show: () => { visible = true; bridge.release(); }, hide: () => { visible = false; } };
}
const tick = () => new Promise((r) => setTimeout(r, 0));

describe('a hidden view', () => {
    test('sends nothing while hidden, receives no topic events, and on becoming visible flushes the held calls in order', async () => {
        const r = rig();
        r.call(1); r.call(2); r.call(3);
        await tick();
        expect(r.callRoute).not.toHaveBeenCalled();
        expect(r.posted).toEqual([]);

        let seen = false;
        const listeners: ((t: string[]) => void)[] = [];
        const delivered: string[] = [];
        const topics = createFrameTopics({ onChange: (fn) => { listeners.push(fn); return () => undefined; }, isLive: () => true }, { hidden: () => false, onVisibilityChange: () => () => undefined });
        const handle = topics.register('u1', (name) => delivered.push(name), () => seen);
        listeners.forEach((fn) => fn(['cplug_topic:u1:runs']));
        expect(delivered).toEqual([]);

        seen = true;
        r.show();
        handle.refresh();
        await tick();
        expect(r.calls).toEqual(['1', '2', '3']);
        expect(r.posted.map((m) => m.id)).toEqual(['c1', 'c2', 'c3']);
        expect(r.posted.every((m) => m.ok === true)).toBe(true);
        expect(delivered).toEqual(['runs']);
    });

    test('the hold is bounded: the ninth held call answers rate_limited, the first eight still run', async () => {
        const r = rig();
        for (let n = 1; n <= 9; n++) r.call(n);
        await tick();
        expect(r.posted).toEqual([{ nonce: NONCE, id: 'c9', ok: false, error: 'rate_limited' }]);
        r.posted.length = 0;
        r.show();
        await tick();
        expect(r.calls).toEqual(['1', '2', '3', '4', '5', '6', '7', '8']);
    });

    test('a call made while visible runs at once', async () => {
        const r = rig();
        r.show();
        r.call(1);
        await tick();
        expect(r.calls).toEqual(['1']);
    });
});
