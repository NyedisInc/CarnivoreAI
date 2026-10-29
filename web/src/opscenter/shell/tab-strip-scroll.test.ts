import { describe, expect, it } from 'vitest';
import { revealTabHorizontally } from './tab-strip-scroll';

describe('selected tab reveal', () => {
  it('moves only the horizontal strip when the selected tab overflows', () => {
    const strip = { scrollLeft: 20, getBoundingClientRect: () => ({ left: 100, right: 300 }) };
    const tab = { getBoundingClientRect: () => ({ left: 280, right: 340 }) };
    revealTabHorizontally(strip as unknown as HTMLElement, tab as unknown as HTMLElement);
    expect(strip.scrollLeft).toBe(60);
    revealTabHorizontally(strip as unknown as HTMLElement,
      { getBoundingClientRect: () => ({ left: 70, right: 120 }) } as unknown as HTMLElement);
    expect(strip.scrollLeft).toBe(30);
    revealTabHorizontally(strip as unknown as HTMLElement,
      { getBoundingClientRect: () => ({ left: 150, right: 210 }) } as unknown as HTMLElement);
    expect(strip.scrollLeft).toBe(30);
  });
});
