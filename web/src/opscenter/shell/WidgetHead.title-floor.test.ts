import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

const src = readFileSync(new URL('./WidgetHead.svelte', import.meta.url), 'utf8');

function rule(sel: string): string {
  const m = src.match(new RegExp(`\\n    ${sel.replace(/[.\[\]>*]/g, '\\$&')} \\{([^}]*)\\}`));
  return m ? m[1]! : '';
}

describe('widget header title floor', () => {
  it('the name has a sensible minimum at every width, still ellipsizing past it', () => {
    const r = rule('.oc-frame-name');
    expect(r).toMatch(/min-width:\s*min\(var\(--oc-frame-name-min\), 100%\)/);
    expect(r).toMatch(/--oc-frame-name-min:\s*1[2-9]ch/);
    expect(r).toMatch(/text-overflow:\s*ellipsis/);
  });
  it('the name does not give up room to the controls before they have shrunk', () => {
    expect(rule('.oc-frame-name')).toMatch(/flex-shrink:\s*0/);
  });
  it('a narrow row (300px and under) still lets the name fall to its few letters', () => {
    expect(src).toMatch(/@container oc-head \(max-width: 300px\)[\s\S]*--oc-frame-name-min:\s*5ch/);
  });
});
