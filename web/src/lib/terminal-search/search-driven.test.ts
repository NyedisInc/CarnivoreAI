import { afterEach, beforeEach, expect, test, vi } from 'vitest';

import { harness } from './search-controller-harness';

beforeEach(() => { vi.useFakeTimers(); });
afterEach(() => { vi.useRealTimers(); });

test('drive opens the search without drawing the box or moving focus', () => {
    const h = harness();
    const input = { focus: vi.fn(), select: vi.fn() } as unknown as HTMLInputElement;
    h.controller.setInputElement(input);
    h.controller.drive();
    expect(h.controller.isOpen()).toBe(true);
    expect(h.controller.driven).toBe(true);
    expect(h.calls.attach).toHaveLength(1);
    expect((input.focus as unknown as ReturnType<typeof vi.fn>)).not.toHaveBeenCalled();
    h.controller.query = 'err';
    h.controller.runQuery();
    expect(h.calls.find.at(-1)?.[0]).toBe('err');
    h.controller.release();
    expect(h.controller.isOpen()).toBe(false);
    expect(h.controller.driven).toBe(false);
    expect(h.calls.focusTerm).toBe(0);
});

test('a user open takes a driven panel back; release then leaves it alone', () => {
    const h = harness();
    const input = { focus: vi.fn(), select: vi.fn() } as unknown as HTMLInputElement;
    h.controller.setInputElement(input);
    h.controller.drive();
    h.controller.open();
    expect(h.controller.driven).toBe(false);
    expect((input.focus as unknown as ReturnType<typeof vi.fn>)).toHaveBeenCalled();
    h.controller.release();
    expect(h.controller.isOpen()).toBe(true);
    h.controller.close();
    expect(h.calls.focusTerm).toBe(1);
});

test('matchCount is the engine count, null until counted', () => {
    const h = harness();
    h.controller.drive();
    expect(h.controller.matchCount).toBeNull();
    h.world.onResults?.({ resultIndex: 0, resultCount: 4, limit: 1000 } as never);
    expect(h.controller.matchCount).toBe(4);
    h.controller.release();
});
