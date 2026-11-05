import { describe, expect, test, vi } from 'vitest';

import { resolveBars } from '../../widget-bars/bar-settings.svelte';
import { RETRACT_MS, type Clock } from '../../widget-bars/bar-state';
import { PANEL_PX, TryScene } from './try-scene.svelte';

function fakeClock(): Clock & { advance(ms: number): void; pending(): number; set: ReturnType<typeof vi.fn> } {
    let now = 0;
    let next = 1;
    const timers = new Map<number, { at: number; fn: () => void }>();
    const set = vi.fn((fn: () => void, ms: number) => { const id = next++; timers.set(id, { at: now + ms, fn }); return id; });
    return {
        set,
        setTimeout: set,
        clearTimeout: (id: unknown) => void timers.delete(id as number),
        advance(ms: number) { now += ms; for (const [id, timer] of [...timers]) if (timer.at <= now) { timers.delete(id); timer.fn(); } },
        pending: () => timers.size,
    };
}

const AUTOHIDE = { side: { mode: 'autohide' }, bottom: { mode: 'autohide' } } as const;
const view = resolveBars({ v: 1, ...AUTOHIDE });

describe('TryScene', () => {
    test('an untouched scene draws handles, arms no timer, and a pointer entering peeks the bar out', () => {
        const clock = fakeClock();
        const scene = new TryScene(clock);
        expect(scene.visual('side', view, true)).toBe('handle');
        expect(scene.visual('bottom', view, true)).toBe('handle');
        expect(clock.set).not.toHaveBeenCalled();
        scene.enter('side');
        expect(scene.visual('side', view, true)).toBe('peek');
        expect(scene.visual('bottom', view, true)).toBe('handle');
    });

    test('leaving retracts after 300 ms, not before, and entering again cancels it', () => {
        const clock = fakeClock();
        const scene = new TryScene(clock);
        scene.enter('side');
        scene.leave('side');
        clock.advance(RETRACT_MS - 1);
        expect(scene.visual('side', view, true)).toBe('peek');
        scene.enter('side');
        clock.advance(RETRACT_MS * 2);
        expect(scene.visual('side', view, true)).toBe('peek');
        scene.leave('side');
        clock.advance(RETRACT_MS);
        expect(scene.visual('side', view, true)).toBe('handle');
        expect(clock.pending()).toBe(0);
    });

    test('a key press opens its sample panel (held); pressing it again closes it and lets go of its pin', () => {
        const scene = new TryScene(fakeClock());
        scene.press('bottom', 'core.shell');
        expect(scene.visual('bottom', view, true)).toBe('held');
        scene.togglePin('bottom');
        expect(scene.edges.bottom.pinnedOn).toBe(0);
        scene.press('bottom', 'core.shell');
        expect(scene.edges.bottom.openKey).toBeNull();
        expect(scene.edges.bottom.pinnedOn).toBeNull();
    });

    test('a panel pinned on one agent shows that agent on its key only while the OTHER agent is active', () => {
        const scene = new TryScene(fakeClock());
        scene.press('side', 'core.notes');
        scene.togglePin('side');
        expect(scene.otherPin('side', 'core.notes')).toBeNull();
        scene.switchAgent();
        expect(scene.otherPin('side', 'core.notes')).toBe(0);
        scene.switchAgent();
        expect(scene.otherPin('side', 'core.notes')).toBeNull();
        scene.togglePin('side');
        scene.switchAgent();
        scene.togglePin('side');
        scene.switchAgent();
        expect(scene.otherPin('side', 'core.notes')).toBe(1);
    });

    test('a pin does nothing while no panel is open, and a different key replaces the open one without keeping the pin', () => {
        const scene = new TryScene(fakeClock());
        scene.togglePin('side');
        expect(scene.edges.side.pinnedOn).toBeNull();
        scene.press('side', 'core.notes');
        scene.togglePin('side');
        scene.press('side', 'core.files');
        expect(scene.edges.side.openKey).toBe('core.files');
        expect(scene.edges.side.pinnedOn).toBeNull();
    });

    test('a panel resizes inside its bounds', () => {
        const scene = new TryScene(fakeClock());
        scene.resize('side', 10);
        expect(scene.edges.side.panelPx).toBe(PANEL_PX.side.min);
        scene.resize('side', 99999);
        expect(scene.edges.side.panelPx).toBe(PANEL_PX.side.max);
        scene.resize('bottom', 250.4);
        expect(scene.edges.bottom.panelPx).toBe(250);
    });

    test('one at a time: opening a panel on one bar folds the other, to its handle', () => {
        const together = resolveBars({ v: 1, ...AUTOHIDE, together: 'one' });
        const scene = new TryScene(fakeClock());
        scene.press('side', 'core.notes');
        expect(scene.visual('bottom', together, true)).toBe('folded');
        scene.press('side', 'core.notes');
        expect(scene.visual('bottom', together, true)).toBe('handle');
    });

    test('a pinned bar stays out in flow, a hidden bar and an empty bar are absent', () => {
        const scene = new TryScene(fakeClock());
        expect(scene.visual('side', resolveBars({ v: 1, side: { mode: 'pinned' } }), true)).toBe('pinned');
        expect(scene.visual('side', resolveBars({ v: 1, side: { show: false } }), true)).toBe('absent');
        expect(scene.visual('side', view, false)).toBe('absent');
    });
});
