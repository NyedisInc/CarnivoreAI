
import { describe, expect, it } from 'vitest';
import { META } from '../meta';
import { resetLayout } from '../model';
import { validate } from '../persist';
import type { SlotId } from '../types';
import { ADAPT_DRIFT, placementDrift, readStoredGrid, toV6 } from './adapt';
import { term, seeded } from './fixtures/helpers';
import { V7_NAMES, v7Layout, v7Page } from './fixtures/v7-layouts';
import { leavesOf, rectsOf } from './tree';
import type { LayoutNode, LayoutV7 } from './types';
import { validateV7 } from './validate';

function expectAdapts(name: string): void {
  const tree = v7Layout(name);
  const page = v7Page(name);
  const adapted = toV6(tree, page);
  const cells = adapted.layout.rows.flatMap((row) => row.slots.map((one) => one.id));
  expect(new Set(cells)).toEqual(new Set(leavesOf(tree.variants.wide.root)));
  if (adapted.outcome === 'adapted') {
    expect(adapted.shortenedSpans).toEqual([]);
    expect(placementDrift(adapted.layout, rectsOf(tree.variants.wide.root))).toBeLessThanOrEqual(ADAPT_DRIFT);
  } else {
    expect(adapted.shortenedSpans.length).toBeGreaterThan(0);
  }
  expect(validate(tree, META, page).refusal).toBeNull();
}

describe('every stored v7 arrangement adapts to v6', () => {
  for (const name of V7_NAMES.filter((one) => one !== 'homeMissingFirstRow')) it(name, () => expectAdapts(name));
  it('the exact arrangements adapt without shortening a span', () => {
    for (const name of ['homeDefault', 'terminalDefault', 'span819', 'stackBelow', 'stackAbove', 'terminal_columns_3', 'terminal_grid_6']) {
      expect(toV6(v7Layout(name), v7Page(name)).outcome).toBe('adapted');
    }
  });
});

function randomTree(random: () => number, tag: string): LayoutNode {
  let leaf = 0;
  let split = 0;
  const grow = (depth: number, parent: 'h' | 'v' | null): LayoutNode => {
    if (depth >= 4 || random() < 0.35) {
      leaf += 1;
      return { t: 'leaf', id: term(`${tag}-${leaf}`) };
    }
    const dir = parent === 'h' ? 'v' : parent === 'v' ? 'h' : random() < 0.5 ? 'h' : 'v';
    const count = 2 + Math.floor(random() * 3);
    const raw = Array.from({ length: count }, () => 0.2 + random());
    const total = raw.reduce((sum, one) => sum + one, 0);
    split += 1;
    const id = `s${split}` as `s${number}`;
    return { t: 'split', id, dir, unit: 'fr', sizes: raw.map((one) => one / total), children: raw.map(() => grow(depth + 1, dir)) };
  };
  return grow(0, null);
}

function doc(root: LayoutNode): LayoutV7 {
  return { v: 7, variants: { wide: { root } }, hidden: [], collapsed: [], heroCollapsed: false };
}

describe('any valid tree adapts without losing a leaf', () => {
  const random = seeded(99);
  let exact = 0;
  for (let run = 0; run < 300; run += 1) {
    const root = randomTree(random, `t${run}`);
    it(`random tree ${run}`, () => {
      const tree = doc(root);
      expect(validateV7(JSON.parse(JSON.stringify(tree)), 'terminal').ok).toBe(true);
      const adapted = toV6(tree, 'terminal');
      const cells = adapted.layout.rows.flatMap((row) => row.slots.map((one) => one.id));
      expect(new Set(cells)).toEqual(new Set(leavesOf(root)));
      expect(cells.length).toBe(leavesOf(root).length);
      if (adapted.outcome === 'adapted') {
        exact += 1;
        expect(placementDrift(adapted.layout, rectsOf(root))).toBeLessThanOrEqual(ADAPT_DRIFT);
      } else {
        expect(adapted.shortenedSpans.length).toBeGreaterThan(0);
      }
    });
  }
  it('more than half of the random trees adapt exactly', () => expect(exact).toBeGreaterThan(150));
});

describe('what v6 cannot say is named, never silent', () => {
  it('two spanners meeting in reverse home-row order clear a span and keep every leaf', () => {
    const [a1, b, c, a2, q, p] = ['a1', 'b', 'c', 'a2', 'q', 'p'].map(term) as SlotId[];
    const root: LayoutNode = {
      t: 'split', id: 's1', dir: 'h', unit: 'fr', sizes: [0.3, 0.2, 0.5],
      children: [
        { t: 'split', id: 's2', dir: 'v', unit: 'fr', sizes: [1 / 3, 1 / 3, 1 / 3],
          children: [{ t: 'leaf', id: a1! }, { t: 'leaf', id: b! }, { t: 'leaf', id: c! }] },
        { t: 'split', id: 's3', dir: 'v', unit: 'fr', sizes: [1 / 3, 2 / 3],
          children: [{ t: 'leaf', id: a2! }, { t: 'leaf', id: q! }] },
        { t: 'leaf', id: p! },
      ],
    };
    const adapted = toV6(doc(root), 'terminal');
    expect(adapted.outcome).toBe('adapted_lossy');
    expect(adapted.shortenedSpans.length).toBeGreaterThan(0);
    expect(new Set(adapted.layout.rows.flatMap((row) => row.slots.map((one) => one.id)))).toEqual(
      new Set([a1, b, c, a2, q, p]),
    );
    const checked = validate(JSON.parse(JSON.stringify(doc(root))), META, 'terminal');
    expect(checked.refusal).toBeNull();
    expect(checked.repaired).toBe(true);
  });
});

describe('readStoredGrid', () => {
  it('hands a v6 value back untouched and names a refused v7', () => {
    const v6 = resetLayout(META, 'terminal');
    expect(readStoredGrid(v6, 'terminal')).toEqual({ kind: 'v6', grid: v6 });
    const bad = readStoredGrid({ v: 7, variants: {}, hidden: [], collapsed: [], heroCollapsed: false }, 'terminal');
    expect(bad.kind).toBe('v7-refused');
  });
});
