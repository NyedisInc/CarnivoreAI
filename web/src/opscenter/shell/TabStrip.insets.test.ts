import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

const src = readFileSync(new URL('./TabStrip.svelte', import.meta.url), 'utf8');
const key = readFileSync(new URL('../../lib/zone-shell/TabKey.svelte', import.meta.url), 'utf8');

function rule(sel: string): string {
  const m = (src + key).match(new RegExp(`\\n\\s*${sel.replace('.', '\\.')} \\{([^}]*)\\}`));
  return m ? m[1]! : '';
}

describe('tab strip side insets (#1632)', () => {
  it('pads the tab label segment on both sides with a token, not a literal', () => {
    expect(rule('.oc-tab')).toMatch(/padding:\s*0 var\(--oc-space-2\);/);
  });
  it('keeps the name ellipsizing so padding is never what shrinks', () => {
    const r = rule('.oc-tab-name');
    expect(r).toMatch(/text-overflow:\s*ellipsis/);
    expect(r).toMatch(/min-width:\s*0/);
  });
  it('keeps a tab minimum wide enough for insets, icon, close and some label', () => {
    const m = rule('.oc-tabwrap').match(/min-width:\s*(\d+)px/);
    expect(Number(m?.[1])).toBeGreaterThanOrEqual(176);
  });
});
