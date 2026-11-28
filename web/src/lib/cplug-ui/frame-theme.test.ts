import { describe, expect, it } from 'vitest';
import { FRAME_OC_TOKENS, isSafeThemeValue } from './frame-theme';

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

describe('FRAME_OC_TOKENS', () => {
  it('includes the full Military Terminal surface, accent, typography, spacing, and motion tokens without duplicates', () => {
    expect(new Set(FRAME_OC_TOKENS).size).toBe(FRAME_OC_TOKENS.length);
    for (const tok of [
      '--oc-orange-bright', '--oc-orange-dim', '--oc-orange-tint',
      '--oc-green-bright', '--oc-green-dim',
      '--oc-surface-1', '--oc-surface-2', '--oc-surface-sunken', '--oc-surface-raised', '--oc-surface-band',
      '--oc-state-hover', '--oc-state-selected', '--oc-ground-chrome', '--oc-line-hairline', '--oc-radius-panel',
      '--oc-fs-micro', '--oc-fs-hint', '--oc-fs-figure', '--oc-tracking-label', '--oc-tracking-caps',
      '--oc-space-0-5', '--oc-space-6', '--oc-motion-fast', '--oc-motion',
    ]) {
      expect(FRAME_OC_TOKENS).toContain(tok);
    }
  });
});
