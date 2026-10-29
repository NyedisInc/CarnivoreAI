import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

const css = readFileSync(new URL('./roster.css', import.meta.url), 'utf8');

describe('pack pane body column', () => {
  it('is a single minmax(0, 1fr) track, so a wide child scrolls inside itself', () => {
    const m = css.match(/\n\.m1-pane__body \{([^}]*)\}/);
    expect(m?.[1] ?? '').toMatch(/grid-template-columns:\s*minmax\(0,\s*1fr\)/);
  });
});
