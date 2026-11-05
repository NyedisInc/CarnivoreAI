import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { GUTTER } from './tracks';

const read = (rel: string): string => readFileSync(new URL(rel, import.meta.url), 'utf8');
const tokens = read('../tokens.css');
const grid = read('./grid.css');
const frame = read('../shell/CellFrame.svelte');

function px(name: string): number {
  const m = tokens.match(new RegExp(`${name}:\\s*(\\d+(?:\\.\\d+)?)px`));
  return m ? Number(m[1]) : NaN;
}

describe('terminal pane frame geometry', () => {
  it('draws the frame with square corners from one token', () => {
    expect(tokens).toMatch(/--oc-radius-frame:\s*0(px)?;/);
    expect(frame).toMatch(/\.oc-frame \{[^}]*border-radius:\s*var\(--oc-radius-frame\)/);
  });

  it('insets the pane area 1 to 2px so a pane never covers a drawer line', () => {
    const inset = px('--oc-pane-inset');
    expect(inset).toBeGreaterThanOrEqual(1);
    expect(inset).toBeLessThanOrEqual(2);
    expect(grid).toMatch(/\.oc-surface-zoomable \{[^}]*margin:\s*var\(--oc-pane-inset\)/);
  });

  it('makes the gutter between zones the drag bar hit width, not extra padding', () => {
    expect(GUTTER).toBe(px('--oc-section-hit'));
  });
});
