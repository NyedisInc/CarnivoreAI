import { describe, expect, test, vi } from 'vitest';
import type { MenuNode } from '../drawer-tabs/add-component-menu';
import { assignMenuKeys } from '../menu-keys/menu-keys';
import { buildWidgetMenu, closing, joinGroups, type WidgetMenuCtx } from './model';
import { barMenuNodes } from './bar-menu';

const leaf = (id: string, extra: Partial<MenuNode> = {}): MenuNode => ({ id, label: id, run: () => {}, ...extra });
const ids = (nodes: readonly MenuNode[]): string[] => nodes.map((n) => n.id);
const breaks = (nodes: readonly MenuNode[]): string[] => nodes.filter((n) => n.sep).map((n) => n.id);

function ctx(extra: Partial<WidgetMenuCtx> = {}): WidgetMenuCtx {
  return {
    editing: false,
    onClose: () => {},
    content: [[leaf('sort:name', { checked: true }), leaf('sort:recent', { checked: false })], [leaf('view-all')]],
    views: [leaf('session', { checked: true }), leaf('all', { checked: false })],
    settings: [[leaf('settings')]],
    popOut: () => {},
    header: { shown: true, toggle: () => {} },
    arrange: [{ item: 'extendRow', run: () => {} }, { item: 'pullBackRow', blocked: 'one row now', run: () => {} }, { item: 'moveToDrawer', run: () => {} }],
    editLayout: () => {},
    close: { run: () => {} },
    ...extra,
  };
}

describe('normal mode', () => {
  test('content, then window (pop out, show header), then edit layout, then close; one hairline per group', () => {
    const menu = buildWidgetMenu(ctx());
    expect(ids(menu)).toEqual(['sort:name', 'sort:recent', 'view-all', 'extend-row', 'pop-out', 'show-header', 'edit-layout', 'close-widget']);
    expect(breaks(menu)).toEqual(['view-all', 'extend-row', 'pop-out', 'edit-layout', 'close-widget']);
  });

  test('extend a row and pull back a row are back in normal mode (Alex (Example-owner), 2026-10-22); pull back only once it covers two rows', () => {
    const extend = vi.fn();
    const pull = vi.fn();
    const arrange = [{ item: 'extendRow' as const, run: extend }, { item: 'pullBackRow' as const, run: pull }, { item: 'moveToDrawer' as const, run: () => {} }];
    const menu = buildWidgetMenu(ctx({ arrange }));
    expect(ids(menu)).toEqual(expect.arrayContaining(['extend-row', 'pull-back-row']));
    expect(ids(menu)).not.toContain('move-to-drawer');
    menu.find((n) => n.id === 'extend-row')!.run!();
    expect(extend).toHaveBeenCalledTimes(1);
    expect(ids(buildWidgetMenu(ctx()))).not.toContain('pull-back-row');
  });

  test('the selected session | all sessions switch is in BOTH modes, after the content (Joe (ccsliinc), 2026-10-19, item 1048)', () => {
    const scopeViews = [leaf('session', { checked: true }), leaf('all', { checked: false })];
    const normal = buildWidgetMenu(ctx({ views: undefined, scopeViews }));
    expect(ids(normal).slice(0, 5)).toEqual(['sort:name', 'sort:recent', 'view-all', 'session', 'all']);
    expect(breaks(normal)).toContain('session');
    const edit = ids(buildWidgetMenu(ctx({ editing: true, views: undefined, scopeViews })));
    expect(edit.filter((id) => id === 'session' || id === 'all')).toEqual(['session', 'all']);
  });

  test('settings, views, move to drawer are edit mode only (Q3 b): none of them is here', () => {
    const menu = ids(buildWidgetMenu(ctx()));
    for (const id of ['settings', 'session', 'all', 'pull-back-row', 'move-to-drawer']) expect(menu).not.toContain(id);
  });

  test('close is last, in the destructive token, and an instance reads remove', () => {
    const menu = buildWidgetMenu(ctx());
    expect(menu[menu.length - 1]).toMatchObject({ id: 'close-widget', danger: true });
    const copy = buildWidgetMenu(ctx({ close: { run: () => {}, instance: true } }));
    expect(copy[copy.length - 1]).toMatchObject({ id: 'remove-widget', danger: true });
  });
});

describe('edit mode (the icon is the gear)', () => {
  test('content, looks, show header, settings, arrange, done editing, close', () => {
    const menu = buildWidgetMenu(ctx({ editing: true }));
    expect(ids(menu)).toEqual([
      'sort:name', 'sort:recent', 'view-all', 'session', 'all', 'show-header', 'settings', 'extend-row', 'pull-back-row', 'move-to-drawer', 'done-editing', 'close-widget',
    ]);
    expect(breaks(menu)).toEqual(['view-all', 'session', 'show-header', 'settings', 'extend-row', 'done-editing', 'close-widget']);
  });

  test('show header is in both modes; pop out is normal mode only', () => {
    expect(ids(buildWidgetMenu(ctx({ editing: false })))).toContain('show-header');
    expect(ids(buildWidgetMenu(ctx({ editing: true })))).toContain('show-header');
    expect(ids(buildWidgetMenu(ctx({ editing: true })))).not.toContain('pop-out');
  });

  test('an arranging entry that applies but not right now is disabled with its reason', () => {
    const pull = buildWidgetMenu(ctx({ editing: true })).find((n) => n.id === 'pull-back-row')!;
    expect(pull.blocked).toBe('one row now');
  });
});

describe('what never applies is left out, never drawn empty', () => {
  test('no pop out, no header tick, no layout, no close: only the content remains and no hairline leads or trails', () => {
    const menu = buildWidgetMenu(ctx({ arrange: [], popOut: null, header: null, editLayout: null, close: null }));
    expect(ids(menu)).toEqual(['sort:name', 'sort:recent', 'view-all']);
    expect(breaks(menu)).toEqual(['view-all']);
  });

  test('a widget with nothing but close has no hairline at all', () => {
    const menu = buildWidgetMenu({ editing: false, onClose: () => {}, close: { run: () => {} } });
    expect(ids(menu)).toEqual(['close-widget']);
    expect(breaks(menu)).toEqual([]);
  });

  test('joinGroups drops empty groups and never doubles a hairline', () => {
    const joined = joinGroups([[], [leaf('a')], [], [leaf('b'), leaf('c')], []]);
    expect(joined.map((n) => [n.id, !!n.sep])).toEqual([['a', false], ['b', true], ['c', false]]);
  });
});

describe('one list for a widget on every surface', () => {
  test('the same context gives the same ids whichever host builds it', () => {
    const grid = ids(buildWidgetMenu(ctx()));
    const drawer = ids(buildWidgetMenu(ctx({ editLayout: () => {} })));
    expect(drawer).toEqual(grid);
  });

  test('the pop-out window offers focus main window in place of pop out, and close', () => {
    const menu = buildWidgetMenu({ editing: false, onClose: () => {}, content: [[leaf('view-all')]], focusMain: () => {}, close: { run: () => {} } });
    expect(ids(menu)).toEqual(['view-all', 'focus-main-window', 'close-widget']);
  });
});

describe('picking an item', () => {
  test('acts, then closes the menu (the host still holds its props while the action reads them); a tick marked keepOpen leaves the menu open', () => {
    const order: string[] = [];
    const onClose = vi.fn(() => order.push('close'));
    const menu = buildWidgetMenu({
      editing: false,
      onClose,
      content: [[leaf('plain', { run: () => order.push('plain') }), leaf('tick', { keepOpen: true, toggle: true, checked: true, run: () => order.push('tick') })]],
    });
    menu.find((n) => n.id === 'plain')!.run!();
    expect(order).toEqual(['plain', 'close']);
    menu.find((n) => n.id === 'tick')!.run!();
    expect(order).toEqual(['plain', 'close', 'tick']);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  test('the menu closes even when the action throws', () => {
    const onClose = vi.fn();
    const [node] = closing([leaf('boom', { run: () => { throw new Error('refused'); } })], onClose);
    expect(() => node!.run!()).toThrow('refused');
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  test('closing walks a branch: its leaves close the menu, its keepOpen ticks do not', () => {
    const onClose = vi.fn();
    const [branch] = closing([{ id: 'b', label: 'b', children: [leaf('x'), leaf('y', { keepOpen: true })] }], onClose);
    branch!.children![0]!.run!();
    expect(onClose).toHaveBeenCalledTimes(1);
    branch!.children![1]!.run!();
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});

describe('the letters (client/js/menu-keys.js): a verb has one letter in every menu', () => {
  test('every core item draws its registered letter and no two of one menu share one', () => {
    for (const editing of [false, true]) {
      const menu = buildWidgetMenu(ctx({ editing }));
      const keys = assignMenuKeys(menu.map((n) => ({ id: n.id, label: n.label })));
      const byId = new Map(menu.map((n, i) => [n.id, keys[i]]));
      expect(byId.get('show-header')).toBe('h');
      expect(byId.get('close-widget')).toBe('k');
      expect(byId.get(editing ? 'done-editing' : 'edit-layout')).toBe('e');
      if (editing) expect(byId.get('settings')).toBe(',');
      else expect(byId.get('pop-out')).toBe('o');
      const drawn = keys.filter(Boolean);
      expect(new Set(drawn).size).toBe(drawn.length);
    }
  });
});

describe('bar sizes live on the bar, not on a widget (Joe (ccsliinc), 2026-10-21)', () => {
  test('a widget menu carries no compact, cozy or detailed rows even when handed a bar size; the bar empty-area menu has them', () => {
    const widget = ids(buildWidgetMenu(ctx({ barSize: { current: 'cozy', set: () => {} } } as Partial<WidgetMenuCtx>)));
    expect(widget.filter((id) => id.startsWith('bar-size'))).toEqual([]);
    expect(widget).not.toContain('pin-bar');
    const bar = barMenuNodes({ size: 'cozy', pinned: false, editing: false, setSize: () => {}, togglePin: () => {}, toggleEdit: () => {}, onClose: () => {} });
    expect(bar.map((n) => n.id).slice(0, 3)).toEqual(['bar-size-compact', 'bar-size-cozy', 'bar-size-detailed']);
  });
});
