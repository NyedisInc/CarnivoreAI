import { readFileSync } from 'node:fs';
import { describe, expect, test } from 'vitest';

const css = readFileSync(new URL('./run-queue.css', import.meta.url), 'utf8');

function body(selector: string): string {
  const at = css.indexOf(`${selector} {`);
  return at < 0 ? '' : css.slice(css.indexOf('{', at) + 1, css.indexOf('}', at));
}

describe('the running and queue strip outlines', () => {
  test('a second section gets one inset line above it, in the rule token', () => {
    expect(body('.oc-rq-section + .oc-rq-section')).toContain('inset 0 1px 0 0 var(--oc-line-rule)');
  });
  test('a head that ends the strip drops its own line (the closing hairline is the one)', () => {
    expect(body('.oc-rq-section:last-child > .oc-rq-head:last-child')).toContain('box-shadow: none');
    expect(body('.oc-rq')).toContain('inset 0 -1px 0 0 var(--oc-line-rule)');
  });
  test('a queue row draws the table grid: a row hairline and column rules on stretched cells, in the shared tokens', () => {
    expect(body('.oc-rq-row')).toContain('inset 0 -1px 0 0 var(--oc-line-faint)');
    expect(body('.oc-rq-row')).toContain('align-items: stretch');
    expect(css).toMatch(/\.oc-rq-area,\s*\.oc-rq-time \{\s*box-shadow: inset 1px 0 0 0 var\(--oc-line-column\)/);
    expect(body('.oc-rq-rows:last-child > .oc-rq-row:last-child')).toContain('box-shadow: none');
  });
});
