import { describe, expect, it } from 'vitest';
import { isSafeThemeValue } from './frame-theme';

describe('isSafeThemeValue', () => {
  it('lets colors and font stacks through', () => {
    expect(isSafeThemeValue('rgb(0, 200, 220)')).toBe(true);
    expect(isSafeThemeValue('#0af')).toBe(true);
    for (const ok of ['rgba(0, 0, 0, 0.5)', 'hsl(180 50% 40%)', 'hsla(180, 50%, 40%, 0.5)', 'color-mix(in srgb, red 40%, blue)', 'var(--x)']) {
      expect(isSafeThemeValue(ok)).toBe(true);
    }
    expect(isSafeThemeValue("'JetBrains Mono', monospace")).toBe(true);
  });

  it('refuses a url() fetch in any spelling', () => {
    expect(isSafeThemeValue('url(//evil.example/p.png)')).toBe(false);
    expect(isSafeThemeValue('URL (x.png)')).toBe(false);
    expect(isSafeThemeValue('image-set(x.png 1x)')).toBe(false);
    expect(isSafeThemeValue('-webkit-image-set(x.png 1x)')).toBe(false);
    expect(isSafeThemeValue('src(x.png)')).toBe(false);
  });

  it('refuses markup characters and over-long values', () => {
    expect(isSafeThemeValue('red;}</style>')).toBe(false);
    expect(isSafeThemeValue('a'.repeat(161))).toBe(false);
  });
});
