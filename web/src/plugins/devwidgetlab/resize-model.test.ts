import { describe, expect, it } from 'vitest';
import { clampBox, dragBox, MAX_BOX, MIN_BOX, nearestSize, stepBox } from './resize-model';
import type { LabSize } from '../sdk/widget-lab';

const size = (name: string, w: number, h: number | null): LabSize => ({ name, w, h, viewport: w, declared: false, floor: false });

describe('the free resize arithmetic', () => {
  it('clamps to the limits and whole pixels', () => {
    expect(clampBox({ w: 1, h: 99999 })).toEqual({ w: MIN_BOX.w, h: MAX_BOX.h });
    expect(clampBox({ w: 200.4, h: 300.6 })).toEqual({ w: 200, h: 301 });
  });

  it('drags one axis for an edge and both for the corner, divided by the zoom', () => {
    expect(dragBox({ w: 300, h: 200 }, 50, 40, 'e', 1)).toEqual({ w: 350, h: 200 });
    expect(dragBox({ w: 300, h: 200 }, 50, 40, 's', 1)).toEqual({ w: 300, h: 240 });
    expect(dragBox({ w: 300, h: 200 }, 50, 40, 'se', 0.5)).toEqual({ w: 400, h: 280 });
  });

  it('drags a slide-out\'s inner edge the real way: left widens, up makes it taller, the other axis never moves', () => {
    expect(dragBox({ w: 378, h: 800 }, -40, 25, 'w', 1)).toEqual({ w: 418, h: 800 });
    expect(dragBox({ w: 1244, h: 318 }, 30, -40, 'n', 1)).toEqual({ w: 1244, h: 358 });
    expect(dragBox({ w: 378, h: 800 }, -40, 0, 'w', 0.5)).toEqual({ w: 458, h: 800 });
    expect(stepBox({ w: 378, h: 800 }, 'ArrowLeft', false, 'w')).toEqual({ w: 386, h: 800 });
    expect(stepBox({ w: 378, h: 800 }, 'ArrowUp', false, 'w')).toBeNull();
    expect(stepBox({ w: 1244, h: 318 }, 'ArrowUp', true, 'n')).toEqual({ w: 1244, h: 350 });
    expect(stepBox({ w: 1244, h: 318 }, 'ArrowRight', false, 'n')).toBeNull();
  });

  it('steps by 8px, 32px with Shift, and ignores any other key', () => {
    expect(stepBox({ w: 300, h: 200 }, 'ArrowRight', false)).toEqual({ w: 308, h: 200 });
    expect(stepBox({ w: 300, h: 200 }, 'ArrowUp', true)).toEqual({ w: 300, h: 168 });
    expect(stepBox({ w: 300, h: 200 }, 'a', false)).toBeNull();
  });

  it('names the nearest published size, by width alone where the size has no fixed height', () => {
    const sizes = [size('s', 200, 150), size('m', 400, 300), size('l', 800, null)];
    expect(nearestSize(sizes, { w: 390, h: 310 })?.name).toBe('m');
    expect(nearestSize(sizes, { w: 780, h: 10 })?.name).toBe('l');
    expect(nearestSize([], { w: 1, h: 1 })).toBeNull();
  });
});
