import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

const css = readFileSync(new URL('./HuddleBody.svelte', import.meta.url), 'utf8').split('<style>')[1] ?? '';

/** The declarations of the LAST rule whose selector is exactly `selector`. */
function rule(selector: string): string {
  const found = [...css.matchAll(/(^|\n)\s*([^{}\n]+)\{([^}]*)\}/g)].filter((m) => (m[2] as string).trim() === selector);
  return (found[found.length - 1]?.[3] as string | undefined) ?? '';
}

const TOP_LINE = /inset 0 1px 0/;

describe('the separator between the list and the add row', () => {
  it('is drawn once, by the add row', () => {
    expect(rule('.hd-add')).toMatch(TOP_LINE);
  });

  it('is not drawn again by the control row above the add row', () => {
    expect(rule('.hd-foot')).not.toMatch(TOP_LINE);
  });

  it('is drawn by the control row only when no add row follows it', () => {
    expect(rule('.hd-foot:not(:has(+ .hd-add))')).toMatch(TOP_LINE);
  });

  it('leaves an empty control row no height, so it cannot show a strip of its own', () => {
    expect(rule('.hd-foot:not(:has(.hd-key))')).toMatch(/display:\s*none/);
  });

  it('pads the add row the same above and below, from one token (Joe, 2026-11-03: top and bottom the same)', () => {
    expect(rule('.hd-add')).toMatch(/padding:\s*var\(--oc-space-2\);/);
  });
});
