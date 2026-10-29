
import { afterEach, describe, expect, it } from 'vitest';
import { fromServerShape, toServerShape } from '../../layouts/shape';
import { parseArrangement } from '../arrangement-model';
import { META } from '../meta';
import { ARRANGERS, DEFAULT_LAYOUT, PRIMARY_SLOT, addInstance, resetLayout } from '../model';
import { flushSave, load, save, storageKey, validate } from '../persist';
import type { Layout } from '../types';
import { toV6 } from './adapt';
import { v7Layout } from './fixtures/v7-layouts';

function installStorage(): Map<string, string> {
  const held = new Map<string, string>();
  (globalThis as unknown as Record<string, unknown>)['localStorage'] = {
    getItem: (key: string) => (held.has(key) ? (held.get(key) as string) : null),
    setItem: (key: string, value: string) => void held.set(key, value),
    removeItem: (key: string) => void held.delete(key),
  };
  return held;
}

afterEach(() => {
  delete (globalThis as unknown as Record<string, unknown>)['localStorage'];
});

function terminalGrid(): Layout {
  let layout = resetLayout(META, 'terminal');
  for (const id of ['row:2', 'row:3', 'row:4']) layout = addInstance(layout, 'terminal', id, '').layout;
  return ARRANGERS.grid(layout);
}

const NOT_CANONICAL = {
  v: 7,
  variants: {
    wide: { root: { t: 'split', id: 's1', dir: 'h', unit: 'fr', sizes: [1], children: [{ t: 'leaf', id: PRIMARY_SLOT }] } },
  },
  hidden: [],
  collapsed: [],
  heroCollapsed: false,
};

describe('persist.ts reads a v7 blob', () => {
  it('validate accepts it and hands back the grid it adapts to, on both pages', () => {
    for (const [name, page] of [
      ['homeDefault', 'home'],
      ['terminalGrid3', 'terminal'],
    ] as const) {
      const checked = validate(v7Layout(name), META, page);
      expect(checked.refusal).toBeNull();
      expect(checked.repaired).toBe(false);
      expect(checked.layout).toEqual(validate(toV6(v7Layout(name), page).layout, META, page).layout);
      expect(checked.layout?.v).toBe(6);
    }
  });

  it('the v6 rules still hold over a v7 blob: a missing singleton is refused as cells', () => {
    const tree = v7Layout('homeDefault');
    const dropped = v7Layout('homeMissingFirstRow');
    expect(validate({ ...tree, variants: dropped.variants }, META, 'home').refusal).toBe('cells');
  });

  it('a malformed tree is refused as tree, and the refusal clears the entry', () => {
    expect(validate(NOT_CANONICAL, META, 'terminal').refusal).toBe('tree');
    const held = installStorage();
    held.set(storageKey('terminal', 'cloude_x'), JSON.stringify(NOT_CANONICAL));
    const opened = load(META, 'terminal', '', 'cloude_x');
    expect(opened.stored).toBe(false);
    expect(opened.notice).not.toBe('');
    expect(held.has(storageKey('terminal', 'cloude_x'))).toBe(false);
  });

  it('load opens a stored v7 layout, and the next save writes v6', () => {
    const held = installStorage();
    const key = storageKey('terminal', 'cloude_x');
    held.set(key, JSON.stringify(v7Layout('terminalGrid3')));
    const opened = load(META, 'terminal', '', 'cloude_x');
    expect(opened.stored).toBe(true);
    expect(opened.notice).toBe('');
    expect(new Set(opened.layout.rows.flatMap((row) => row.slots.map((one) => one.id)))).toEqual(
      new Set(terminalGrid().rows.flatMap((row) => row.slots.map((one) => one.id))),
    );
    save(opened.layout, 'terminal', 'cloude_x');
    flushSave('terminal', 'cloude_x');
    expect(JSON.parse(held.get(key) as string).v).toBe(6);
  });
});

describe('the synced arrangement reads a v7 entry', () => {
  it('adapts a valid tree to v6 and drops a malformed one to null', () => {
    const parsed = parseArrangement({
      v: 1,
      sessions: {
        good: { layout: v7Layout('terminalGrid3'), groups: {} },
        bad: { layout: NOT_CANONICAL, groups: { [PRIMARY_SLOT]: { tabs: [PRIMARY_SLOT] } } },
        old: { layout: terminalGrid(), groups: {} },
      },
    })!;
    expect(parsed.sessions['good']!.layout?.v).toBe(6);
    expect(validate(parsed.sessions['good']!.layout, META, 'terminal').refusal).toBeNull();
    expect(parsed.sessions['bad']!.layout).toBeNull();
    expect(parsed.sessions['bad']!.groups).toEqual({ [PRIMARY_SLOT]: { tabs: [PRIMARY_SLOT] } });
    expect(parsed.sessions['old']!.layout).toEqual(terminalGrid());
  });
});

describe('a saved Layout reads a v7 shape', () => {
  function saved(): { layout: Layout; groups: Record<string, { tabs: string[] }> } {
    return toServerShape(terminalGrid(), {}, 1) as never;
  }

  it('draws the same grid as its v6 twin', () => {
    const v6 = saved();
    const v7 = { ...v6, layout: v7Layout('terminalGrid3') as unknown as Layout };
    const fromV6 = fromServerShape(v6, 3)!;
    const fromV7 = fromServerShape(v7, 3)!;
    expect(fromV7.groups).toEqual(fromV6.groups);
    expect(validate(fromV7.layout, META, 'terminal').layout).toEqual(validate(fromV6.layout, META, 'terminal').layout);
  });

  it('a malformed tree falls back to one row of the components', () => {
    const drawn = fromServerShape(
      { layout: NOT_CANONICAL as unknown as Layout, groups: { 'terminal:row:1': { tabs: ['terminal:row:1', 'terminal:row:2'] } } },
      1,
    )!;
    expect(drawn.layout!.rows.length).toBe(1);
    expect(drawn.layout!.rows[0]!.slots.map((one) => one.id)).toEqual([PRIMARY_SLOT]);
  });
});
