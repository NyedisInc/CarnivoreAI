import { describe, expect, it, vi } from 'vitest';
import type { MenuNode } from './add-component-menu';
import { findByPath, isRemotable, nextRemoteMenuId, remoteMenuHost, setRemoteMenuHost, toWire } from './menu-remote';

const run = vi.fn();
const tree: MenuNode[] = [
  { id: 'a', label: 'show header', run, checked: true, toggle: true },
  { id: 'more', label: 'more', children: [{ id: 'x', label: 'deep', run, blocked: 'preview only' }, { id: 'sep', label: '', sep: true }] },
];

describe('menu-remote', () => {
  it('sends plain data only: no function crosses, a leaf with a run says so, a branch carries its children', () => {
    const wire = toWire(tree);
    expect(JSON.parse(JSON.stringify(wire))).toEqual(wire);
    expect(wire[0]).toEqual({ id: 'a', label: 'show header', checked: true, toggle: true, runs: true });
    expect(wire[1]!.children![0]).toEqual({ id: 'x', label: 'deep', blocked: 'preview only', runs: true });
    expect(wire[1]!.runs).toBeUndefined();
  });

  it('finds an item by its path of ids, and answers null for a path that leads nowhere', () => {
    expect(findByPath(tree, ['more', 'x'])?.label).toBe('deep');
    expect(findByPath(tree, ['a'])?.run).toBe(run);
    expect(findByPath(tree, ['more', 'nope'])).toBeNull();
    expect(findByPath(tree, ['nope'])).toBeNull();
  });

  it('keeps a menu local when any item cannot cross (swatches, session marks, raw markup, a locked item), at any depth', () => {
    expect(isRemotable(tree)).toBe(true);
    expect(isRemotable([{ id: 's', label: 's', swatches: [] } as unknown as MenuNode])).toBe(false);
    expect(isRemotable([{ id: 'g', label: 'g', glyphHtml: '<b/>' } as unknown as MenuNode])).toBe(false);
    expect(isRemotable([{ id: 'p', label: 'p', children: [{ id: 'l', label: 'l', locked: true } as unknown as MenuNode] }])).toBe(false);
  });

  it('installs and removes its host, and hands out fresh ids', () => {
    expect(remoteMenuHost()).toBeNull();
    const host = { show: vi.fn(), hide: vi.fn() };
    setRemoteMenuHost(host);
    expect(remoteMenuHost()).toBe(host);
    setRemoteMenuHost(null);
    expect(remoteMenuHost()).toBeNull();
    expect(nextRemoteMenuId()).toBeLessThan(nextRemoteMenuId());
  });
});
