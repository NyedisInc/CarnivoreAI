/** @vitest-environment jsdom */
import { describe, expect, test, vi } from 'vitest';
import type { ThemeRegistry } from '../cplugs/sdk/themes';

vi.stubGlobal('OffscreenCanvas', class {
  getContext(): object {
    let fill = '#000000';
    let pixel = [0, 0, 0, 0];
    return {
      get fillStyle(): string { return fill; },
      set fillStyle(v: string) { if (/^#[0-9a-f]{6}$/i.test(v)) fill = v.toLowerCase(); },
      clearRect(): void { pixel = [0, 0, 0, 0]; },
      fillRect(): void { pixel = [1, 3, 5].map((i) => parseInt(fill.slice(i, i + 2), 16)).concat(255); },
      getImageData(): { data: Uint8ClampedArray } { return { data: Uint8ClampedArray.from(pixel) }; },
    };
  }
});
document.documentElement.style.setProperty('--oc-light-line-l', '0.6');

const { frameScheme } = await import('./theme-scheme');

const THEMES: { id: string; cssVars: Record<string, string> }[] = [
  { id: 'carnivore-light', cssVars: { '--color-bg-page': '#eceeef' } },
  { id: 'dracula', cssVars: { '--color-bg-page': '#282a36' } },
  { id: 'groundless', cssVars: { '--color-accent': '#ff0000' } },
];
const HOST: ThemeRegistry = {
  listAll: () => THEMES,
  getActiveGlobal: () => ({ id: 'dracula', cssVars: { '--color-bg-page': '#282a36' } }),
};

describe('frameScheme', () => {
  test("a frame takes its framed theme's own scheme", () => {
    expect(frameScheme('carnivore-light', HOST)).toBe('light');
    expect(frameScheme('dracula', HOST)).toBe('dark');
  });
  test("no theme named: the page's active one", () => {
    expect(frameScheme(null, HOST)).toBe('dark');
  });
  test('an unknown theme or one with no ground gives none, so the frame keeps the page scheme', () => {
    expect(frameScheme('nope', HOST)).toBeUndefined();
    expect(frameScheme('groundless', HOST)).toBeUndefined();
  });
});
