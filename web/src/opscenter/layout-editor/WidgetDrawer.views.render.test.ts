/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { installPopoverPolyfill } from '../../lib/popover-jsdom-polyfill';
import { flushSync, mount, unmount } from 'svelte';

vi.mock('../../lib/item-settings/store.svelte', () => ({ isWidgetDisabled: () => false }));
vi.mock('../../lib/help/feature-media', () => ({
  fetchFeatureMediaBlob: () => Promise.reject(new Error('no server in this test')),
}));

import WidgetDrawer from './WidgetDrawer.svelte';
import Icon from '../ui/Icon.svelte';
import { homeLayout } from '../engine/layout.svelte';
import { CELL_IDS, META } from '../engine/meta';
import { CORE_MANIFESTS } from '../widgets/core-manifests';
import { hasViews } from '../widgets/views';
import { hasOptions } from '../../lib/widget-menu/option-nodes';
import { editorSeams, enterLayoutEditor, finishLayoutEditor } from './editor.svelte';
import { dismissRefusal } from '../widgets/chrome/refusal-toast.svelte';
import { widgetDrawerView } from './drawer-view-pref.svelte';

const real = { ...editorSeams };
let app: ReturnType<typeof mount> | null = null;

const cards = (): HTMLButtonElement[] => [...document.querySelectorAll<HTMLButtonElement>('[data-le-card][data-widget]')];
const card = (widget: string): HTMLButtonElement | null => document.querySelector(`[data-le-card][data-widget="${widget}"]`);
const toggle = (type: string): HTMLButtonElement => document.querySelector(`[data-drawer-type-toggle="${type}"]`)!;
const search = (): HTMLInputElement => document.querySelector('[data-layout-editor-search]')!;
const titles = (root: ParentNode = document): string[] =>
  [...root.querySelectorAll('[data-le-card][data-widget] .le-card__name')].map((el) => el.textContent ?? '');
const type = (value: string): void => {
  search().value = value;
  search().dispatchEvent(new Event('input', { bubbles: true }));
  flushSync();
};

beforeEach(() => {
  localStorage.clear();
  widgetDrawerView.reset();
  homeLayout.resetAll();
  editorSeams.page = () => 'home';
  editorSeams.store = (p) => (p === 'home' ? homeLayout : null);
  editorSeams.wide = () => true;
  enterLayoutEditor();
  app = mount(WidgetDrawer, { target: document.body, props: { store: homeLayout, page: 'home' } });
  flushSync();
});

afterEach(() => {
  if (app) unmount(app);
  app = null;
  finishLayoutEditor();
  dismissRefusal();
  Object.assign(editorSeams, real);
  document.body.replaceChildren();
});

installPopoverPolyfill();

describe('one icon per widget', () => {
  test('every manifest carries the icon and tone of the cell record the home frame draws from', () => {
    for (const id of CELL_IDS) {
      const manifest = CORE_MANIFESTS[`core.${id}`]!;
      expect(manifest.icon, id).toBe(META[id].icon);
      expect(manifest.iconTone, id).toBe(META[id].iconTone);
    }
  });

  test('every drawer row shows its registered icon, drawn exactly as the frame draws that icon', () => {
    const rows = cards();
    expect(rows.length).toBeGreaterThan(10);
    for (const row of rows) {
      const manifest = CORE_MANIFESTS[row.dataset['widget']!]!;
      const tile = row.querySelector<HTMLElement>('.le-ico[data-widget-icon]')!;
      expect(tile.dataset['widgetIcon'], manifest.id).toBe(manifest.icon);
      const reference = document.createElement('div');
      const ref = mount(Icon, { target: reference, props: { name: manifest.icon, size: 18 } });
      flushSync();
      expect(tile.querySelector('svg')!.innerHTML, manifest.id).toBe(reference.querySelector('svg')!.innerHTML);
      unmount(ref);
      expect(tile.style.color, manifest.id).toBe(`var(--${manifest.iconTone})`);
    }
  });

  test('the icon is the default: a widget with a screenshot still leads with its icon, not a preview', () => {
    expect(card('core.notes')!.querySelector('.le-thumb')).toBeNull();
    expect(card('core.notes')!.querySelector('.le-ico svg')).not.toBeNull();
  });
});

describe('the views', () => {
  test('the tree by type is the default: a fold per type, its widgets sorted by name', () => {
    expect(document.querySelector('[data-drawer-view="type"]')!.getAttribute('aria-pressed')).toBe('true');
    const folds = [...document.querySelectorAll<HTMLElement>('[data-drawer-type]')];
    const order = folds.map((fold) => fold.dataset['drawerType']!);
    expect(order).toEqual([...order].sort((a, b) => a.localeCompare(b)));
    for (const fold of folds) {
      const names = titles(fold);
      expect(names.length).toBeGreaterThan(0);
      expect(names).toEqual([...names].sort((a, b) => a.localeCompare(b, undefined, { sensitivity: 'base' })));
    }
  });

  test('by name is one flat list sorted by name, with no folds', () => {
    document.querySelector<HTMLButtonElement>('[data-drawer-view="name"]')!.click();
    flushSync();
    expect(document.querySelector('[data-drawer-type]')).toBeNull();
    const names = titles();
    expect(names.length).toBe(cards().length);
    expect(names).toEqual([...names].sort((a, b) => a.localeCompare(b, undefined, { sensitivity: 'base' })));
    expect(widgetDrawerView.mode).toBe('name');
  });

  test('a type fold closes and opens; Shift closes every type', () => {
    const first = document.querySelector<HTMLElement>('[data-drawer-type]')!.dataset['drawerType']!;
    toggle(first).click();
    flushSync();
    expect(toggle(first).getAttribute('aria-expanded')).toBe('false');
    expect(document.querySelector(`[data-drawer-type="${first}"] [data-le-card]`)).toBeNull();
    toggle(first).click();
    flushSync();
    expect(toggle(first).getAttribute('aria-expanded')).toBe('true');
    toggle(first).dispatchEvent(new MouseEvent('click', { bubbles: true, shiftKey: true }));
    flushSync();
    for (const fold of document.querySelectorAll<HTMLButtonElement>('[data-drawer-type-toggle]')) {
      expect(fold.getAttribute('aria-expanded')).toBe('false');
    }
  });
});

describe('the fuzzy search', () => {
  test('keeps fuzzy matches, highlights the matched letters, ranks the best first', () => {
    document.querySelector<HTMLButtonElement>('[data-drawer-view="name"]')!.click();
    type('nts');
    const names = titles();
    expect(names.length).toBeGreaterThan(0);
    expect(names.length).toBeLessThan(cards().length + 100);
    const hits = [...(card('core.notes') ?? document.body).querySelectorAll('mark.le-hit')].map((m) => m.textContent);
    expect(hits.join('')).toBe('nts');
    expect(card('core.notes')!.querySelector('.le-card__name')!.textContent).toBe('notes');
  });

  test('a better match comes before a worse one in the flat list', () => {
    document.querySelector<HTMLButtonElement>('[data-drawer-view="name"]')!.click();
    type('note');
    expect(cards()[0]!.dataset['widget']).toBe('core.notes');
  });

  test('no match says so', () => {
    type('qqqzzzq');
    expect(cards()).toHaveLength(0);
    expect(document.querySelector('.le-empty')).not.toBeNull();
  });

  test('the tree opens every fold while searching without storing them, and the folds come back when cleared', () => {
    const first = document.querySelector<HTMLElement>('[data-drawer-type]')!.dataset['drawerType']!;
    toggle(first).click();
    flushSync();
    expect([...widgetDrawerView.folded]).toEqual([first]);
    type('e');
    for (const fold of document.querySelectorAll<HTMLButtonElement>('[data-drawer-type-toggle]')) {
      expect(fold.getAttribute('aria-expanded')).toBe('true');
    }
    expect([...widgetDrawerView.folded]).toEqual([first]);
    toggle(first).click();
    expect([...widgetDrawerView.folded]).toEqual([first]);
    type('');
    expect(toggle(first).getAttribute('aria-expanded')).toBe('false');
  });
});

describe('the options mark', () => {
  test('a card shows it exactly for a widget with views, settings or per-copy options, with a tooltip', () => {
    let marked = 0;
    for (const row of cards()) {
      const manifest = CORE_MANIFESTS[row.dataset['widget']!]!;
      const mark = row.querySelector<HTMLElement>('[data-widget-options]');
      expect(!!mark, manifest.id).toBe(hasOptions(manifest, manifest, true));
      if (mark) {
        marked += 1;
        expect(mark.getAttribute('title')).toBe('has configurable views or settings');
        expect(row.getAttribute('aria-label')).toContain('has configurable views or settings');
      }
    }
    expect(marked).toBeGreaterThan(0);
    expect(hasViews(CORE_MANIFESTS['core.tasks'])).toBe(true);
    expect(card('core.tasks')!.querySelector('[data-widget-options]')).not.toBeNull();
    expect(card('core.stat-running')!.querySelector('[data-widget-options]')).toBeNull();
  });
});

describe('no reordering inside the drawer (issue #1676)', () => {
  test('no row or fold is a drag-reorder target and no handle is drawn', () => {
    expect(document.querySelector('[draggable="true"], [data-sortable], [data-reorder], [data-drag-handle], .le-handle, .le-grip')).toBeNull();
  });

  test('the type folds are drawn in alphabetical order', () => {
    const drawn = [...document.querySelectorAll('[data-drawer-type]')].map((el) => el.getAttribute('data-drawer-type') ?? '');
    expect(drawn.length).toBeGreaterThan(1);
    expect(drawn).toEqual([...drawn].sort((a, b) => a.localeCompare(b)));
  });
});
