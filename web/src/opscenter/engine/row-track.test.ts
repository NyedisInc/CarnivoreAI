import { describe, expect, it } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const css = fs.readFileSync(
  path.join(path.dirname(fileURLToPath(import.meta.url)), 'grid.css'),
  'utf8',
);

function ruleBody(selector: string): string {
  const at = css.indexOf(`\n${selector} {`);
  if (at < 0) return '';
  const open = css.indexOf('{', at);
  const close = css.indexOf('}', open);
  return close < 0 ? '' : css.slice(open + 1, close);
}

describe('.oc-row declares its own single track', () => {
  it('is found at all, so the assertions below are not looking at nothing', () => {
    expect(ruleBody('.oc-row').length).toBeGreaterThan(20);
  });

  it('pins the track to the row height rather than letting it size to content', () => {
    expect(ruleBody('.oc-row')).toMatch(/grid-template-rows:\s*100%/);
  });

  it('still lets the phone stack size its own rows', () => {
    expect(css).toMatch(/grid-template-rows:\s*none/);
  });
});
