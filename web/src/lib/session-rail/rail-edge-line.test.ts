import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, test } from 'vitest';

const grip = readFileSync(join(process.cwd(), 'src/lib/session-rail/RailResizeHandle.svelte'), 'utf8');
const out = readFileSync(join(process.cwd(), 'src/lib/session-rail/RailSlideout.svelte'), 'utf8');

/** The declarations of the first rule whose selector is exactly `selector`. */
function rule(selector: string): string {
  const start = grip.indexOf(`${selector} {`);
  expect(start, selector).toBeGreaterThan(-1);
  return grip.slice(start, grip.indexOf('}', start));
}

describe('slide-out edge line geometry', () => {
  test('the line is 2px and the hit area stays 8px, reaching 5px over the grid', () => {
    const shared = rule('.rail-grip');
    expect(shared).toContain('--edge-line: 2px;');
    expect(shared).toContain('--edge-hit: 8px;');
    expect(shared).toContain('--edge-reach: 5px;');
  });
  test('both edges size the line from the one token, flush at the reach', () => {
    for (const [edge, offset, size, grab] of [['side', 'left', 'width', 'left'], ['bottom', 'top', 'height', 'top']] as const) {
      const lines = rule(`.rail-grip--${edge} .rail-edge__line`);
      expect(lines).toContain(`${offset}: var(--edge-reach);`);
      expect(lines).toContain(`${size}: var(--edge-line);`);
      const box = rule(`.rail-grip--${edge}`);
      expect(box).toContain(`${grab}: calc(-1 * var(--edge-reach));`);
      expect(box).toContain(`${size}: var(--edge-hit);`);
    }
  });
  test('the line is not layered above anything on its own (the grip stays at z-index 2)', () => {
    expect(rule('.rail-grip')).toContain('z-index: 2;');
    expect(rule('.rail-edge__line')).not.toMatch(/z-index/);
  });
  test('the panels paint no hairline outside their top or left face (it sat over the session highlight, the panel being z-index 40)', () => {
    const at = (selector: string): string => out.slice(out.indexOf(`${selector} {`), out.indexOf('}', out.indexOf(`${selector} {`)));
    expect(at('.rail-out--side')).not.toMatch(/^\s*box-shadow:/m);
    expect(at('.rail-out--bottom')).toContain('box-shadow: 1px 0 0 0 var(--oc-line-frame);');
    expect(at('.rail-out--bottom')).not.toMatch(/0 -1px/);
  });
});
