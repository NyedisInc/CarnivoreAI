
import { describe, expect, it } from 'vitest';
import type { SlotId } from '../types';
import { term } from './fixtures/helpers';
import { canonicalize, leavesOf, rectsOf, removeLeaf, splitsOf, terminalSlotsOf, withoutSlot } from './tree';
import type { LayoutNode, LayoutV7, SplitNode } from './types';

const leaf = (id: SlotId): LayoutNode => ({ t: 'leaf', id });
const h = (id: number, sizes: number[], children: LayoutNode[]): SplitNode => ({
  t: 'split',
  id: `s${id}`,
  dir: 'h',
  unit: 'fr',
  sizes,
  children,
});
const v = (id: number, sizes: number[], children: LayoutNode[], unit: 'fr' | 'px' = 'fr'): SplitNode => ({
  t: 'split',
  id: `s${id}`,
  dir: 'v',
  unit,
  sizes,
  children,
});
const [A, B, C, D] = ['a', 'b', 'c', 'd'].map(term) as [SlotId, SlotId, SlotId, SlotId];

describe('walk order', () => {
  it('is depth first, first child first', () => {
    const tree = h(1, [0.5, 0.5], [v(2, [0.5, 0.5], [leaf(A), leaf(C)]), leaf(B)]);
    expect(leavesOf(tree)).toEqual([A, C, B]);
    expect(splitsOf(tree).map((one) => one.id)).toEqual(['s1', 's2']);
  });

  it('terminalSlotsOf keeps terminals only, in walk order, the v7 twin of _grid_terminal_slots', () => {
    const tree = v(1, [300, 400], [h(2, [0.5, 0.5], ['notes' as SlotId, A].map(leaf)), leaf(B)], 'px');
    const layout: LayoutV7 = { v: 7, variants: { wide: { root: tree } }, hidden: [], collapsed: [], heroCollapsed: false };
    expect(terminalSlotsOf(layout)).toEqual([A, B]);
  });
});

describe('canonical form', () => {
  it('flattens a same-direction child without moving any box', () => {
    const tree = h(1, [0.5, 0.5], [leaf(A), h(2, [0.5, 0.5], [leaf(B), leaf(C)])]);
    const made = canonicalize(tree, 'terminal');
    expect(made).toEqual(h(1, [0.5, 0.25, 0.25], [leaf(A), leaf(B), leaf(C)]));
    expect(rectsOf(made)).toEqual(rectsOf(tree));
  });

  it('replaces a single-child split by its child', () => {
    expect(canonicalize(h(1, [1], [leaf(A)]), 'terminal')).toEqual(leaf(A));
  });

  it('keeps the home px root even with one child, and flattens a v child into px', () => {
    const one = v(1, [500], [leaf(A)], 'px');
    expect(canonicalize(one, 'home')).toBe(one);
    const nested = v(1, [600], [v(2, [0.25, 0.75], [leaf(A), leaf(B)])], 'px');
    expect(canonicalize(nested, 'home')).toEqual(v(1, [150, 450], [leaf(A), leaf(B)], 'px'));
  });

  it('is idempotent and hands back the same object when already canonical', () => {
    const tree = h(1, [0.3, 0.7], [leaf(A), v(2, [0.5, 0.5], [leaf(B), leaf(C)])]);
    expect(canonicalize(tree, 'terminal')).toBe(tree);
    const once = canonicalize(h(1, [0.5, 0.5], [leaf(A), h(2, [1], [h(3, [0.5, 0.5], [leaf(B), leaf(C)])])]), 'terminal');
    expect(canonicalize(once, 'terminal')).toBe(once);
  });
});

describe('removing a leaf, the v7 twin of _drop_cell', () => {
  it('renormalises the siblings and collapses a split left with one child', () => {
    const tree = h(1, [0.5, 0.5], [leaf(A), v(2, [0.25, 0.75], [leaf(B), leaf(C)])]);
    expect(removeLeaf(tree, B, 'terminal')).toEqual(h(1, [0.5, 0.5], [leaf(A), leaf(C)]));
    const three = h(1, [0.2, 0.3, 0.5], [leaf(A), leaf(B), leaf(C)]);
    const out = removeLeaf(three, A, 'terminal') as SplitNode;
    expect(out.children).toEqual([leaf(B), leaf(C)]);
    expect(out.sizes[0]).toBeCloseTo(0.375, 12);
    expect(out.sizes[1]).toBeCloseTo(0.625, 12);
  });

  it('shortens the home page rather than stretching the rest', () => {
    const tree = v(1, [200, 300], [leaf(A), leaf(B)], 'px');
    expect(removeLeaf(tree, A, 'home')).toEqual(v(1, [300], [leaf(B)], 'px'));
  });

  it('answers null when nothing is left, and the same tree when the leaf was absent', () => {
    expect(removeLeaf(leaf(A), A, 'terminal')).toBeNull();
    const tree = h(1, [0.5, 0.5], [leaf(A), leaf(B)]);
    expect(removeLeaf(tree, D, 'terminal')).toBe(tree);
  });

  it('withoutSlot drops the slot from the tree and both side lists', () => {
    const layout: LayoutV7 = {
      v: 7,
      variants: { wide: { root: h(1, [0.5, 0.5], [leaf(A), leaf(B)]) } },
      hidden: [C],
      collapsed: [A, C],
      heroCollapsed: false,
    };
    const out = withoutSlot(layout, A, 'terminal');
    expect(out?.variants.wide.root).toEqual(leaf(B));
    expect(out?.collapsed).toEqual([C]);
    expect(withoutSlot(out!, B, 'terminal')).toBeNull();
  });
});

describe('geometry', () => {
  it('draws px roots in pixels and everything under them by share', () => {
    const rects = rectsOf(v(1, [100, 300], [leaf(A), h(2, [0.25, 0.75], [leaf(B), leaf(C)])], 'px'));
    expect(rects.get(A)).toEqual({ x0: 0, x1: 1, y0: 0, y1: 100 });
    expect(rects.get(C)).toEqual({ x0: 0.25, x1: 1, y0: 100, y1: 400 });
  });
});
