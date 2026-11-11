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

    it('an attachable-only row (uuid, no session_id) never counts as live: no open, no adopt; the wake id opens by id', async () => {
        const rows = [{ name: 'carnivore_x', session_uuid: 'u1', session_id: null as string | null }];
        const isLive = (u: string, id?: string | null) => !!id || rows.some((r) => r.session_uuid === u && !!r.session_id);
        const polls: number[] = [];
        const h = host({ isLive, openRow: async (u, id) => { h.calls.push(`open:${u}:${id ?? ''}:${polls.length}`); } });
        h.sleep = async () => { polls.push(1); if (polls.length === 2) rows[0]!.session_id = 'ses_1'; };
        expect(await afterWake('u1', 'nav', h)).toBe('opened');
        expect(h.calls).toEqual(['open:u1::2']);
        const h2 = host({ isLive, openRow: async (u, id) => { h2.calls.push(`open:${u}:${id}`); } });
        rows[0]!.session_id = null;
        expect(await afterWake('u1', 'nav', h2, 'ses_9')).toBe('opened');
        expect(h2.calls).toEqual(['open:u1:ses_9']);
    });
});
