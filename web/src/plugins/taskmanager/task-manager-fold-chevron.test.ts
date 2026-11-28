import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const HEADERS = ['TaskManagerProjectHead', 'TaskManagerStatusSections', 'TaskManagerSections', 'TaskManagerSubHead'];
const read = (f: string): string => readFileSync(resolve(__dirname, f), 'utf8');

describe('huddle fold chevrons (#1651)', () => {
  for (const name of HEADERS) {
    it(`${name} draws the shared FoldChevron, not a per-header icon`, () => {
      const src = read(`${name}.svelte`);
      expect(src).toContain('<FoldChevron />');
      expect(src).not.toMatch(/name=\{[^}]*'chevron-(right|down)'/);
    });
  }

  it('the shared component carries the left bar glyph and the rotation rule is keyed on aria-expanded', () => {
    const chevron = readFileSync(resolve(__dirname, '../../opscenter/ui/FoldChevron.svelte'), 'utf8');
    expect(chevron).toContain('viewBox="0 0 12 12"');
    expect(chevron).toContain('stroke-width="2"');
    expect(chevron).toContain('M4 2l4 4-4 4');
    const css = readFileSync(resolve(__dirname, '../../../../client/css/session-sidebar-groups.css'), 'utf8');
    expect(css).toMatch(/\[aria-expanded="true"\] > \.session-sidebar-group__gutter > \.session-sidebar-group__chevron[^{]*\{\s*transform: rotate\(90deg\)/);
    expect(css).toMatch(/prefers-reduced-motion: reduce\)\s*\{\s*\.session-sidebar-group__chevron\s*\{\s*transition: none/);
  });
});
