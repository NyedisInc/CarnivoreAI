/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { installPopoverPolyfill } from '../../lib/popover-jsdom-polyfill';
import { flushSync, mount, unmount } from 'svelte';

const switchedOff = vi.hoisted(() => new Set<string>());
vi.mock('../../lib/item-settings/store.svelte', () => ({
  isWidgetDisabled: (id: string) => switchedOff.has(id),
}));
vi.mock('../../lib/help/feature-media', () => ({
  fetchFeatureMediaBlob: () => Promise.reject(new Error('no server in this test')),
}));

import WidgetDrawer from './WidgetDrawer.svelte';
import { homeLayout } from '../engine/layout.svelte';
import { editorSeams, enterLayoutEditor, finishLayoutEditor, layoutEditor, removeWidget } from './editor.svelte';
import { dismissRefusal, placementRefusal } from '../widgets/chrome/refusal-toast.svelte';

const real = { ...editorSeams };
let app: ReturnType<typeof mount> | null = null;

const cards = (): HTMLButtonElement[] => [...document.querySelectorAll<HTMLButtonElement>('.le-card[data-widget]')];
const card = (widget: string): HTMLButtonElement | null =>
  document.querySelector<HTMLButtonElement>(`.le-card[data-widget="${widget}"]`);
const placed = (): string[] => homeLayout.state.layout.rows.flatMap((row) => row.slots.map((slot) => slot.id));

beforeEach(() => {
  switchedOff.clear();
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

describe('the list', () => {
  test('every widget off this screen is an addable card, every placed one says it is on this page', () => {
    const addable = cards().filter((c) => c.dataset['state'] === 'addable' && !('family' in c.dataset)).map((c) => c.dataset['widget']);
    expect(addable).toEqual(
      expect.arrayContaining(['core.questions', 'core.files', 'core.keep-awake', 'core.machine-stats', 'core.notes', 'core.scheduled-tasks']),
    );
    for (const widget of addable) expect(placed()).not.toContain(widget!.slice('core.'.length));
    const stats = card('core.stat-running')!;
    expect(stats.dataset['state']).toBe('placed');
    expect(stats.getAttribute('aria-disabled')).toBe('false');
    expect(stats.classList.contains('le-card--placed')).toBe(false);
    expect(stats.textContent).toContain('on home');
    expect(cards().every((c) => c.querySelector('.le-ico[data-widget-icon] svg'))).toBe(true);
    expect(cards().some((c) => c.querySelector('[data-row-sizes]') || /\d+ x \d+/.test(c.textContent ?? ''))).toBe(false);
  });

  test('the tree by type is the default, no old family headings; the analytics family folds open', () => {
    expect(document.querySelector('.le-ghead')).toBeNull();
    expect(document.querySelector('[data-drawer-type]')).not.toBeNull();
    const family = card('core.analytics')!;
    expect(family.dataset['state']).toBe('addable');
    expect(family.getAttribute('aria-expanded')).toBe('false');
    family.click();
    flushSync();
    expect(family.getAttribute('aria-expanded')).toBe('true');
    expect(document.querySelector('.le-gallery')).not.toBeNull();
  });

  test('the analytics fold is clean: one inset column, section labels, presets as two-line rows', () => {
    card('core.analytics')!.click();
    flushSync();
    const fold = document.querySelector<HTMLElement>('[data-analytics-fold]')!;
    expect(fold.classList.contains('le-gallery')).toBe(true);
    expect(fold.querySelector('.le-gallery__label')!.textContent).toBe('analytics gallery');
    expect(fold.querySelectorAll('[data-gallery-category]').length).toBeGreaterThan(1);
    const presets = [...fold.querySelectorAll<HTMLElement>('[data-preset]')];
    expect(presets.length).toBeGreaterThan(3);
    for (const preset of presets) {
      expect(preset.querySelector('.le-gallery__name')!.textContent!.length).toBeGreaterThan(0);
      expect(preset.querySelector('.le-gallery__note .le-gallery__viz')).not.toBeNull();
      expect(preset.querySelector('.le-card__meta')).toBeNull();
      expect(preset.getAttribute('title')).toBeTruthy();
    }
    const hint = fold.querySelector('.le-gallery__hint')!;
    expect(hint.previousElementSibling?.classList.contains('le-gallery__cards')).toBe(true);
  });

  test('one list: no shelf for the sidebar widget area or the glance area follows it', () => {
    expect(document.querySelector('[data-zone-shelf]')).toBeNull();
    expect(document.querySelector('[data-zone-card]')).toBeNull();
    expect(document.querySelector('[data-glance-shelf]')).toBeNull();
    expect(document.querySelectorAll('.le-list')).toHaveLength(1);
    expect(card('core.ledger')).not.toBeNull();
    expect(card('core.notes')).not.toBeNull();
  });

  test('no pills under find: the find box and one kind filter share a line; the filter keeps one kind', () => {
    expect(document.querySelector('[data-drawer-kinds]')).toBeNull();
    expect(document.querySelector('[data-drawer-kind]')).toBeNull();
    expect(document.querySelector('[data-drawer-toggle]')).toBeNull();
    expect(document.querySelector('.le-tools .le-chip')).toBeNull();
    const line = document.querySelector<HTMLElement>('.le-find')!;
    const input = line.querySelector<HTMLInputElement>('[data-layout-editor-search]')!;
    const filter = line.querySelector<HTMLSelectElement>('select[data-drawer-kind-filter]')!;
    expect(input).not.toBeNull();
    expect([...filter.options].map((o) => o.value)).toEqual(['', 'kpi', 'list', 'monitor', 'feed', 'tool', 'pane', 'chart']);
    const every = cards().length;
    filter.value = 'tool';
    filter.dispatchEvent(new Event('change', { bubbles: true }));
    flushSync();
    expect(cards().length).toBeGreaterThan(0);
    expect(cards().every((c) => c.dataset['type'] === 'tool')).toBe(true);
    expect(card('core.notes')).not.toBeNull();
    expect(card('core.ledger')).toBeNull();
    input.value = 'files';
    input.dispatchEvent(new Event('input', { bubbles: true }));
    flushSync();
    expect(cards().map((c) => c.dataset['widget'])).toEqual(['core.files']);
    filter.value = '';
    filter.dispatchEvent(new Event('change', { bubbles: true }));
    input.value = '';
    input.dispatchEvent(new Event('input', { bubbles: true }));
    flushSync();
    expect(cards().length).toBe(every);
  });

  test('the (i) opens the description card under its row, and closes it again', () => {
    const info = document.querySelector<HTMLButtonElement>('[data-widget-info-open="core.notes"]')!;
    expect(info.closest('.le-card')).toBeNull();
    expect(info.getAttribute('aria-expanded')).toBe('false');
    info.click();
    flushSync();
    expect(info.getAttribute('aria-expanded')).toBe('true');
    const described = document.querySelector<HTMLElement>('[data-widget-description="core.notes"]')!;
    expect(described).not.toBeNull();
    expect(document.getElementById(info.getAttribute('aria-controls')!)?.contains(described)).toBe(true);
    expect(described.querySelector('[data-widget-info-about]')!.textContent).toBe('a note kept with the session or the page, in markdown.');
    expect(described.querySelector('.le-thumb')).not.toBeNull();
    expect(described.querySelector('[data-widget-info-fact="sizes"]')).toBeNull();
    expect(described.textContent).not.toMatch(/\d+ ?x ?\d+/);
    expect(described.querySelector('[data-widget-info-fact="places"]')!.textContent).toContain('a dashboard');
    expect(described.querySelector('[data-widget-info-fact="maker"]')!.textContent).toBe('built in');
    expect(described.querySelector('[data-widget-info-fact="options"]')).not.toBeNull();
    expect(described.querySelector('[data-widget-info-fact="zones"]')).toBeNull();
    expect(placed()).not.toContain('notes');
    info.click();
    flushSync();
    expect(document.querySelector('[data-widget-description="core.notes"]')).toBeNull();
  });

  test('a switched-off widget is listed, dimmed, with why; no toggle or hidden count under the list', () => {
    unmount(app!);
    switchedOff.add('core.notes');
    app = mount(WidgetDrawer, { target: document.body, props: { store: homeLayout, page: 'home' } });
    flushSync();
    expect(document.querySelector('[data-drawer-toggle="show-refused"]')).toBeNull();
    expect(document.querySelector('[data-drawer-tally]')).toBeNull();
    expect(card('core.files')).not.toBeNull();
    const notes = card('core.notes')!;
    expect(notes.dataset['state']).toBe('refused');
    expect(notes.textContent).toContain('switched off on the widgets page');
    const before = placed();
    notes.click();
    flushSync();
    expect(placementRefusal.line).toBe('notes is switched off on the widgets page');
    expect(placed()).toEqual(before);
  });

  test('search narrows, and Escape in the search clears it without ending the edit', () => {
    const input = document.querySelector<HTMLInputElement>('[data-layout-editor-search]')!;
    expect(card('core.analytics')).not.toBeNull();
    input.value = 'keep';
    input.dispatchEvent(new Event('input', { bubbles: true }));
    flushSync();
    expect(cards().map((c) => c.dataset['widget'])).toEqual(['core.keep-awake']);
    input.value = 'nothing like this';
    input.dispatchEvent(new Event('input', { bubbles: true }));
    flushSync();
    expect(cards()).toEqual([]);
    expect(document.querySelector('.le-empty')?.textContent).toBe('no widgets match');
    const esc = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true });
    input.dispatchEvent(esc);
    flushSync();
    expect(input.value).toBe('');
    expect(esc.defaultPrevented).toBe(true);
    expect(layoutEditor.active).toBe(true);
    expect(card('core.analytics')).not.toBeNull();
  });

  test('the analytics family answers to a gallery preset name and opens its fold', () => {
    const input = document.querySelector<HTMLInputElement>('[data-layout-editor-search]')!;
    input.value = 'chart';
    input.dispatchEvent(new Event('input', { bubbles: true }));
    flushSync();
    expect(card('core.analytics')).not.toBeNull();
    expect(document.querySelector('.le-gallery')).not.toBeNull();
    expect(document.querySelector('.le-empty')).toBeNull();
  });
});

describe('adding and the foot', () => {
  test('a click adds the widget at its designed place; the card then reads on screen', async () => {
    card('core.notes')!.click();
    await vi.waitFor(() => expect(placed()).toContain('notes'));
    flushSync();
    expect(card('core.notes')!.dataset['state']).toBe('placed');
    const before = JSON.stringify(homeLayout.state.layout);
    card('core.stat-running')!.click();
    flushSync();
    expect(JSON.stringify(homeLayout.state.layout)).toBe(before);
    expect(document.querySelector('[data-duplicate-prompt="here"]')?.textContent).toContain('already here');
  });

  test('the foot is the Done button alone: no undo, reset or cancel', () => {
    const buttons = [...document.querySelectorAll<HTMLButtonElement>('.le-foot button')];
    expect(buttons).toHaveLength(1);
    expect(buttons[0]!.hasAttribute('data-layout-editor-done')).toBe(true);
    expect(document.querySelector('[data-layout-editor-undo], [data-layout-editor-reset], [data-layout-editor-cancel], .le-confirm')).toBeNull();
  });

  test('a change stays with no Done, and Done only leaves the mode', async () => {
    card('core.notes')!.click();
    await vi.waitFor(() => expect(placed()).toContain('notes'));
    document.querySelector<HTMLButtonElement>('[data-layout-editor-done]')!.click();
    flushSync();
    expect(layoutEditor.active).toBe(false);
    expect(placed()).toContain('notes');
  });

  test('a removed widget is listed as addable in the drawer and a click puts it back', async () => {
    expect(card('core.stat-running')!.dataset['state']).toBe('placed');
    await removeWidget('stat-running');
    flushSync();
    expect(placed()).not.toContain('stat-running');
    expect(card('core.stat-running')!.dataset['state']).toBe('addable');
    card('core.stat-running')!.click();
    await vi.waitFor(() => expect(placed()).toContain('stat-running'));
  });
});
