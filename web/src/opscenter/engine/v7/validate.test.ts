
import { describe, expect, it } from 'vitest';
import { v7Layout } from './fixtures/v7-layouts';
import type { V7Refusal } from './types';
import { MAX_PX_SIZE, validateNode, validateV7 } from './validate';

const leaf = (id: string) => ({ t: 'leaf', id });
const split = (id: string, dir: string, sizes: unknown, children: unknown[], unit = 'fr') => ({
  t: 'split',
  id,
  dir,
  unit,
  sizes,
  children,
});
const doc = (root: unknown, extra: Record<string, unknown> = {}) => ({
  v: 7,
  variants: { wide: { root } },
  hidden: [],
  collapsed: [],
  heroCollapsed: false,
  ...extra,
});
const two = split('s1', 'h', [0.5, 0.5], [leaf('terminal:a'), leaf('terminal:b')]);

describe('accepts', () => {
  it('the stored home default and a two-up terminal', () => {
    expect(validateV7(v7Layout('homeDefault'), 'home').ok).toBe(true);
    expect(validateV7(doc(two), 'terminal').ok).toBe(true);
    expect(validateV7(doc(leaf('terminal:@primary')), 'terminal').ok).toBe(true);
  });

  it('a nested widget area at depth 2 is fr throughout, even on home', () => {
    expect(validateNode(two, { page: 'home', areaDepth: 2 }).ok).toBe(true);
  });
});

describe('refuses, naming the rule', () => {
  const cases: [string, unknown, V7Refusal, 'home' | 'terminal'][] = [
    ['not an object', [], 'malformed', 'terminal'],
    ['an unknown top field', { ...doc(two), extra: 1 }, 'unknown-field', 'terminal'],
    ['a v6 value', { v: 6, rows: [] }, 'version', 'terminal'],
    ['an unknown size class', { ...doc(two), variants: { wide: { root: two }, narrow: { root: two } } }, 'variants', 'terminal'],
    ['a missing wide variant', { ...doc(two), variants: {} }, 'variants', 'terminal'],
    ['an unknown node type', doc({ t: 'tabs', id: 'x' }), 'node', 'terminal'],
    ['an unknown node field', doc({ t: 'leaf', id: 'terminal:a', span: 2 }), 'unknown-field', 'terminal'],
    ['a bad split id', doc(split('r1', 'h', [0.5, 0.5], [leaf('terminal:a'), leaf('terminal:b')])), 'split-id', 'terminal'],
    [
      'a repeated split id',
      doc(split('s1', 'h', [0.5, 0.5], [leaf('terminal:a'), split('s1', 'v', [0.5, 0.5], [leaf('terminal:b'), leaf('terminal:c')])])),
      'split-id',
      'terminal',
    ],
    ['an unknown leaf id', doc(leaf('not-a-cell')), 'leaf-id', 'terminal'],
    ['a leaf twice', doc(split('s1', 'h', [0.5, 0.5], [leaf('terminal:a'), leaf('terminal:a')])), 'duplicate-leaf', 'terminal'],
    ['a bad direction', doc(split('s1', 'x', [0.5, 0.5], [leaf('terminal:a'), leaf('terminal:b')])), 'dir', 'terminal'],
    ['px on the terminal page', doc(split('s1', 'v', [300, 300], [leaf('terminal:a'), leaf('terminal:b')], 'px')), 'unit', 'terminal'],
    ['an unknown unit', doc(split('s1', 'v', [0.5, 0.5], [leaf('terminal:a'), leaf('terminal:b')], 'em')), 'unit', 'terminal'],
    ['sizes not summing to 1', doc(split('s1', 'h', [0.5, 0.6], [leaf('terminal:a'), leaf('terminal:b')])), 'sizes', 'terminal'],
    ['one size too few', doc(split('s1', 'h', [1], [leaf('terminal:a'), leaf('terminal:b')])), 'sizes', 'terminal'],
    ['a zero size', doc(split('s1', 'h', [0, 1], [leaf('terminal:a'), leaf('terminal:b')])), 'sizes', 'terminal'],
    ['no children list', doc({ t: 'split', id: 's1', dir: 'h', unit: 'fr', sizes: [] }), 'children', 'terminal'],
    ['a split with one child', doc(split('s1', 'h', [1], [leaf('terminal:a')])), 'single-child', 'terminal'],
    [
      'a split inside the same direction',
      doc(split('s1', 'h', [0.5, 0.5], [leaf('terminal:a'), split('s2', 'h', [0.5, 0.5], [leaf('terminal:b'), leaf('terminal:c')])])),
      'same-dir',
      'terminal',
    ],
    ['a home root that is a leaf', doc(leaf('terminal:a')), 'home-root', 'home'],
    ['a home root that is fr', doc(two), 'home-root', 'home'],
    ['a px size past the bound', doc(split('s1', 'v', [MAX_PX_SIZE + 1], [leaf('terminal:a')], 'px')), 'sizes', 'home'],
    [
      'px below the home root',
      doc(split('s1', 'v', [500], [split('s2', 'h', [100, 100], [leaf('terminal:a'), leaf('terminal:b')], 'px')], 'px')),
      'unit',
      'home',
    ],
    ['a slot both hidden and placed', doc(two, { hidden: ['terminal:a'] }), 'hidden', 'terminal'],
    ['a hidden list that is not a list', doc(two, { hidden: 'x' }), 'hidden', 'terminal'],
    ['a collapsed slot twice', doc(two, { collapsed: ['terminal:a', 'terminal:a'] }), 'collapsed', 'terminal'],
    ['a non-boolean heroCollapsed', doc(two, { heroCollapsed: 'yes' }), 'hero-collapsed', 'terminal'],
    ['a value over the byte cap', doc(two, { collapsed: Array.from({ length: 1200 }, (_, at) => `terminal:t${at}`) }), 'oversize', 'terminal'],
  ];
  for (const [name, value, refusal, page] of cases) {
    it(name, () => {
      const check = validateV7(value, page);
      expect(check.ok).toBe(false);
      if (!check.ok) {
        expect(check.refusal).toBe(refusal);
        expect(check.detail.length).toBeGreaterThan(0);
      }
    });
  }

  it('a tree deeper than the bound', () => {
    let node: unknown = leaf('terminal:deep');
    for (let at = 0; at < 20; at += 1) {
      node = split(`s${at + 1}`, at % 2 ? 'h' : 'v', [0.5, 0.5], [node, leaf(`terminal:x${at}`)]);
    }
    const check = validateV7(doc(node), 'terminal');
    expect(check.ok ? null : check.refusal).toBe('depth');
  });

  it('a tree with more nodes than the bound', () => {
    const rows = Array.from({ length: 40 }, (_, row) =>
      split(`s${row + 2}`, 'h', Array(8).fill(1 / 8), Array.from({ length: 8 }, (_, at) => leaf(`terminal:${row}-${at}`))),
    );
    const check = validateNode(split('s1', 'v', Array(40).fill(1 / 40), rows), { page: 'terminal' });
    expect(check.ok ? null : check.refusal).toBe('nodes');
  });

  it('a widget area nested past two levels', () => {
    const check = validateNode(two, { page: 'terminal', areaDepth: 3 });
    expect(check.ok ? null : check.refusal).toBe('area-depth');
  });

  it('an injected slot check is honoured', () => {
    const check = validateV7(doc(two), 'terminal', (id) => id !== 'terminal:b');
    expect(check.ok ? null : check.refusal).toBe('leaf-id');
  });
});

describe('default slot id check (u162-01)', () => {
  it('refuses Object.prototype names as leaf ids', async () => {
    const { defaultIsSlotId } = await import('./validate');
    for (const name of ['constructor', 'toString', 'hasOwnProperty', '__proto__']) {
      expect(defaultIsSlotId(name)).toBe(false);
    }
    expect(defaultIsSlotId('terminal:a')).toBe(true);
  });
});
