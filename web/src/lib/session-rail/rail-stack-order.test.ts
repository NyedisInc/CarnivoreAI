/* the bottom bar */
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, test } from 'vitest';

const surface = readFileSync(join(process.cwd(), 'src/opscenter/TerminalSurface.svelte'), 'utf8');
const layer = readFileSync(join(process.cwd(), 'src/lib/session-rail/rail-layer.css'), 'utf8');

describe('the side bar paints over the bottom bar', () => {
  test('the two bars share one layer, so mount order decides who is on top', () => {
    expect(layer.match(/z-index: 45;/g)).toHaveLength(1);
    expect(layer).not.toMatch(/\.rail--bottom \.rail__layer[^{]*\{[^}]*z-index/);
  });
  test('the side bar mounts after the bottom bar', () => {
    const side = surface.indexOf('<SessionRail edge="side" />');
    const bottom = surface.indexOf('<SessionRail edge="bottom" />');
    expect(side).toBeGreaterThan(-1);
    expect(bottom).toBeGreaterThan(-1);
    expect(side).toBeGreaterThan(bottom);
  });
});
