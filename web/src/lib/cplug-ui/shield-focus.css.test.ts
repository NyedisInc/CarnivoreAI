import { readFileSync } from 'node:fs';
import { describe, expect, test } from 'vitest';

const css = readFileSync(new URL('./cplug-ui.css', import.meta.url), 'utf8');

/** The declaration block of the one rule with this exact selector. Inputs: selector. Output: its body text, or ''. */
function body(selector: string): string {
  const at = css.indexOf(`${selector} {`);
  return at < 0 ? '' : css.slice(css.indexOf('{', at) + 1, css.indexOf('}', at));
}

describe('the panel click shield wears the shared focus rule', () => {
  test('it reserves a 1px transparent border and names the hue the focus rule brightens', () => {
    const shield = body('.cu-gate__shield');
    expect(shield).toMatch(/border:\s*1px solid transparent/);
    expect(shield).toMatch(/--_bd:\s*var\(--oc-focus-quiet\)/);
    expect(shield).not.toMatch(/border:\s*0\b/);
  });
});
