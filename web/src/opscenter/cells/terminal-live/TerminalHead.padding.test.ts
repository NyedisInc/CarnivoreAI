import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const src = fs.readFileSync(path.join(__dirname, 'TerminalHead.svelte'), 'utf8');

function block(selector: string): string {
  const at = src.indexOf(`${selector} {`);
  expect(at).toBeGreaterThan(-1);
  return src.slice(at, src.indexOf('}', at)).replace(/\/\*[\s\S]*?\*\//g, '');
}

describe('tabbed terminal head spacing', () => {
  const rule = block('.oc-tl-head-tabbed');
  it('pads the row top and bottom with a token', () => {
    expect(rule).toMatch(/padding-block:\s*var\(--oc-space-\d\)/);
  });
  it('keeps a token gap between its rows', () => {
    expect(rule).toMatch(/gap:\s*var\(--oc-space-\d\)/);
    expect(rule).not.toMatch(/gap:\s*0;/);
  });
  it('uses no literal colors', () => {
    expect(rule).not.toMatch(/#[0-9a-f]{3,6}|rgb\(/i);
  });
});

describe('tabbed terminal head side insets', () => {
  it('leaves the side inset to the title row alone, with no dead padding-left override', () => {
    const at = src.indexOf(':global(.oc-frame-title:has(> .oc-tl-head-tabbed)) {');
    expect(at).toBeGreaterThan(-1);
    const rule = src.slice(at, src.indexOf('}', at)).replace(/\/\*[\s\S]*?\*\//g, '');
    expect(rule).not.toMatch(/padding-(left|right|inline)/);
  });
});

describe('frameless terminal head side insets', () => {
  it('insets only the head drawn with no frame row above it, by the title-row token', () => {
    expect(src).toMatch(/const framed = \$derived\(!!frameHeader\?\.drawn\);/);
    expect(src).toMatch(/class:oc-tl-head-bare=\{!framed\}/);
    expect(block('.oc-tl-head-bare')).toMatch(/padding-inline:\s*var\(--oc-space-3\)/);
    expect(block('.oc-tl-head')).toMatch(/padding:\s*0;/);
  });
});
