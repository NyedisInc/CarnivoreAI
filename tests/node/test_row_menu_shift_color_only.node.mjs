import { readFileSync } from 'node:fs';
import assert from 'node:assert/strict';

const css = readFileSync(new URL('../../client/css/session-row-menu.css', import.meta.url), 'utf8');
const blocks = [...css.matchAll(/([^{}]*data-shift-restart[^{}]*)\{([^}]*)\}/g)];
assert.ok(blocks.length > 0, 'shift rule exists');
for (const [, sel, body] of blocks) {
  assert.match(body, /color:\s*var\(--oc-yellow\)/, `color token in: ${sel.trim()}`);
  assert.doesNotMatch(body, /border|box-shadow|outline|background/, `no ring props in: ${sel.trim()}`);
}
console.log('ok');
