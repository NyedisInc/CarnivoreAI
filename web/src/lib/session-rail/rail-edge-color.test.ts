import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, test } from 'vitest';

const here = join(process.cwd(), 'src/lib/session-rail');
const grip = readFileSync(join(here, 'RailResizeHandle.svelte'), 'utf8');
const layer = readFileSync(join(here, 'rail-layer.css'), 'utf8');

function rule(css: string, selector: string): string {
  const start = css.indexOf(`${selector} {`);
  expect(start, selector).toBeGreaterThan(-1);
  return css.slice(start, css.indexOf('}', start));
}

describe('slide-out edge color', () => {
  test('the shared line rule rests in --oc-line-frame', () => {
    expect(rule(grip, '.rail-edge__line')).toContain('background: var(--oc-line-frame);');
  });
  test('neither edge overrides the resting color', () => {
    for (const sel of ['.rail-grip--side', '.rail-grip--bottom']) {
      expect(rule(grip, sel)).not.toMatch(/background|--rail-edge-rest|--oc-line-panel/);
    }
    expect(grip).not.toContain('--oc-line-panel);\n      transition');
  });
  test('the bars own hairlines use the same token', () => {
    expect(rule(layer, '.rail__layer')).toContain('inset 1px 0 0 0 var(--oc-line-frame)');
    expect(rule(layer, '.rail--bottom .rail__layer')).toContain('inset 0 1px 0 0 var(--oc-line-frame)');
  });
});
