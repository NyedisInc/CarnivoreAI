import { describe, expect, it, vi } from 'vitest';
import { afterWake, type WakeFocusHost } from './wake-focus';

function host(over: Partial<WakeFocusHost> & { liveAfter?: number } = {}): WakeFocusHost & { calls: string[] } {
    const calls: string[] = [];
    let polls = 0;
    const liveAfter = over.liveAfter ?? 0;
    return {
        calls,
        keep: () => true,
        isLive: () => polls++ >= liveAfter,
        inShowingLayout: () => false,
        focusMember: (u) => { calls.push(`focus:${u}`); return true; },
        openRow: async (u) => { calls.push(`open:${u}`); },
        sleep: async () => {},
        ...over,
    };
}

describe('wake focus', () => {
    it('focuses the tab when the woken session is in the showing layout', async () => {
        const h = host({ inShowingLayout: () => true, liveAfter: 2 });
        expect(await afterWake('u1', 'nav', h)).toBe('layout');
        expect(h.calls).toEqual(['focus:u1']);
    });

    it('calls the shared open path when the session is in no layout', async () => {
        const h = host();
        expect(await afterWake('u1', 'nav', h)).toBe('opened');
        expect(h.calls).toEqual(['open:u1']);
    });

    it('opens when the layout holds no tab for it', async () => {
        const h = host({ inShowingLayout: () => true, focusMember: () => false });
        expect(await afterWake('u1', 'nav', h)).toBe('opened');
        expect(h.calls).toEqual(['open:u1']);
    });

    it('a navigation between the click and the live session cancels silently', async () => {
        let current = true;
        const h = host({ liveAfter: 1, keep: () => current, sleep: async () => { current = false; } });
        expect(await afterWake('u1', 'nav', h)).toBe('cancelled');
        expect(h.calls).toEqual([]);
    });

    it('gives up quietly when the session never goes live', async () => {
        const h = host({ isLive: () => false });
        const spy = vi.spyOn(h, 'openRow');
        expect(await afterWake('u1', 'nav', h)).toBe('timeout');
        expect(spy).not.toHaveBeenCalled();
    });
});
