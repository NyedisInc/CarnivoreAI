import { describe, expect, test } from 'vitest';
import { resetLayout } from '../engine/model';
import { META } from '../engine/meta';
import type { LayoutPage, SlotId } from '../engine/types';
import { WIDGET_CATEGORIES } from '../widgets/types';
import { isViewCell } from '../widgets/views';
import { CORE_MANIFESTS } from '../widgets/core-manifests';
import { categoryKey, chipCategories, drawerItems, offered, type DrawerInputs } from './drawer-model';

function inputs(page: LayoutPage, over: Partial<DrawerInputs> = {}): DrawerInputs {
  const layout = resetLayout(META, page);
  return {
    page,
    onSurface: layout.rows.flatMap((row) => row.slots.map((slot) => slot.id as SlotId)),
    disabled: () => false,
    query: '',
    category: null,
    t: (key) => key,
    ...over,
  };
}

describe('what the drawer offers', () => {
  test('home: every singleton off the surface is addable, every placed one is listed as placed', () => {
    const base = inputs('home');
    const items = offered(base);
    const addable = items.filter((item) => item.state === 'addable').map((item) => item.cell);
    const placed = items.filter((item) => item.state === 'placed').map((item) => item.cell);
    const singletons = Object.values(CORE_MANIFESTS)
      .filter((m) => m.instancing === 'singleton' && !isViewCell(m))
      .map((m) => m.id.slice('core.'.length))
      .filter((cell) => !base.onSurface.includes(cell as SlotId));
    expect(addable.sort()).toEqual(singletons.sort());
    expect(placed.length).toBeGreaterThan(0);
    for (const cell of placed) expect(base.onSurface).toContain(cell);
    const firstPlaced = items.findIndex((item) => item.state === 'placed');
    expect(items.slice(firstPlaced).every((item) => item.state === 'placed')).toBe(true);
  });

  test('a per-target kind (terminal, browser) is never a card: it needs a session', () => {
    const cells = offered(inputs('terminal')).map((item) => item.widgetId);
    expect(cells).not.toContain('core.terminal');
    expect(cells).not.toContain('core.browser');
  });

  test('a widget of another page is offered too: no zone or canvas gates the list', () => {
    const homeOnly = Object.values(CORE_MANIFESTS).find(
      (m) => m.instancing === 'singleton' && !m.canvases.includes('terminal'),
    );
    expect(homeOnly).toBeDefined();
    const cell = homeOnly!.id.slice('core.'.length) as SlotId;
    const item = offered(inputs('terminal')).find((one) => one.cell === cell);
    expect(item?.state).toBe('addable');
  });

  test('a switched-off widget is never offered, placed or not', () => {
    const base = inputs('home');
    const off = new Set(['core.notes', 'core.stat-running']);
    const items = offered({ ...base, disabled: (id) => off.has(id) });
    const ids = items.map((item) => item.widgetId);
    expect(ids).not.toContain('core.notes');
    expect(ids).not.toContain('core.stat-running');
    const again = offered(base).map((item) => item.widgetId);
    expect(again).toContain('core.notes');
    expect(again).toContain('core.stat-running');
  });

  test('nothing is addable on a screen that already holds every widget', () => {
    const every = Object.values(CORE_MANIFESTS).map((m) => m.id.slice('core.'.length) as SlotId);
    const items = offered(inputs('home', { onSurface: every }));
    expect(items.length).toBeGreaterThan(0);
    expect(items.every((item) => item.state === 'placed')).toBe(true);
  });
});

describe('narrowing', () => {
  test('search matches the name, the category name and the id, ignoring case', () => {
    const base = inputs('home', { t: (key) => (key === META.notes.titleKey ? 'Notes' : key) });
    const byName = drawerItems({ ...base, query: '  NOTE ' });
    expect(byName.map((item) => item.cell)).toEqual(['notes']);
    const byId = drawerItems({ ...base, query: 'core.stat-running' });
    expect(byId.map((item) => item.cell)).toEqual(['stat-running']);
    const byCategory = drawerItems({ ...base, query: categoryKey('monitoring') });
    expect(byCategory.length).toBeGreaterThan(0);
    expect(byCategory.every((item) => item.manifest.category === 'monitoring')).toBe(true);
    expect(drawerItems({ ...base, query: 'no such widget anywhere' })).toEqual([]);
  });

  test('a chip keeps one category; the chip row lists only categories present', () => {
    const base = inputs('home');
    const tools = drawerItems({ ...base, category: 'tools' });
    expect(tools.length).toBeGreaterThan(0);
    expect(tools.every((item) => item.manifest.category === 'tools')).toBe(true);
    const chips = chipCategories(offered(base), WIDGET_CATEGORIES);
    expect(chips).not.toContain('live');
    expect(chips).toEqual(WIDGET_CATEGORIES.filter((c) => chips.includes(c)));
  });
});
