import { expect, it, vi } from 'vitest';
import { reapplyForViewClass } from './class-flip';

it('a phone-line crossing refetches so the new class filters apply, and repaints when the drawer is shut', () => {
    const open = { refreshNow: vi.fn(() => Promise.resolve()), repaint: vi.fn() };
    reapplyForViewClass(open);
    expect(open.refreshNow).toHaveBeenCalledTimes(1);
    expect(open.repaint).not.toHaveBeenCalled();
    const shut = { refreshNow: vi.fn(() => undefined), repaint: vi.fn() };
    reapplyForViewClass(shut);
    expect(shut.repaint).toHaveBeenCalledTimes(1);
});
