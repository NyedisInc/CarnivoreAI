import { describe, expect, it } from 'vitest';
import { EDGE, placeMenu } from './add-component-menu';

const view = { width: 1440, height: 900 };
const size = { width: 220, height: 160 };

describe('placeMenu keeps a menu inside the window', () => {
  it('opens under the opener when it fits, its top-left at the opener\'s bottom-left (the row kebab ask, 2026-09-22)', () => {
    const p = placeMenu({ left: 100, top: 100, right: 130, bottom: 130 }, null, size, view);
    expect(p.top).toBe(134);
    expect(p.left).toBe(100);
  });

  it('flips over an opener on the bottom edge instead of running off the window', () => {
    const opener = { left: 100, top: 860, right: 130, bottom: 890 };
    const p = placeMenu(opener, null, size, view);
    expect(p.top + size.height).toBeLessThanOrEqual(opener.top - 4);
    expect(p.top).toBeGreaterThanOrEqual(EDGE);
  });

  it('keeps a submenu of a bottom-edge menu inside the window', () => {
    const p = placeMenu({ left: 100, right: 320, top: 850, bottom: 850 }, { left: 100, right: 320, top: 700, bottom: 700 }, size, view);
    expect(p.top + size.height).toBeLessThanOrEqual(view.height - EDGE);
  });

  const host = { left: 1200, right: 1390, top: 300, bottom: 520 };
  const item = { left: 1200, right: 1390, top: 480, bottom: 504 };

  it('flips a fold-out to the host\'s left when there is no room on its right', () => {
    const p = placeMenu(item, host, size, view);
    expect(p.left + size.width).toBeLessThanOrEqual(host.left + 8);
    expect(p.left).toBeGreaterThanOrEqual(EDGE);
  });

  it('keeps a fold-out on the right when it fits', () => {
    const near = { left: 100, right: 290, top: 300, bottom: 520 };
    const p = placeMenu({ left: 100, right: 290, top: 300, bottom: 324 }, near, size, view);
    expect(p.left).toBe(near.right - 8);
    expect(p.left + size.width).toBeLessThanOrEqual(view.width - EDGE);
  });

  it('shifts a fold-out up off the bottom edge and caps its height', () => {
    const p = placeMenu({ left: 100, right: 290, top: 880, bottom: 904 }, { left: 100, right: 290, top: 700, bottom: 900 }, size, view);
    expect(p.top + size.height).toBeLessThanOrEqual(view.height - EDGE);
    expect(p.top + p.maxHeight).toBeLessThanOrEqual(view.height - EDGE);
  });

  it('pins a fold-out taller than the window to the top edge and lets it scroll', () => {
    const tall = { width: 220, height: 2000 };
    const p = placeMenu({ left: 100, right: 290, top: 400, bottom: 424 }, { left: 100, right: 290, top: 300, bottom: 600 }, tall, view);
    expect(p.top).toBe(EDGE);
    expect(p.maxHeight).toBe(view.height - 2 * EDGE);
  });

  it('never leaves a fold-out past either side of a window narrower than two menus', () => {
    const narrow = { width: 300, height: 900 };
    const p = placeMenu({ left: 20, right: 280, top: 100, bottom: 124 }, { left: 20, right: 280, top: 80, bottom: 400 }, size, narrow);
    expect(p.left).toBeGreaterThanOrEqual(EDGE);
    expect(p.left + size.width).toBeLessThanOrEqual(narrow.width - EDGE);
  });
});
