/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync } from 'svelte';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

vi.mock('../../opscenter/api', async (importOriginal) => {
  const real = await importOriginal<Record<string, unknown>>();
  return { ...real, sessions: { data: [] }, primarySessionId: () => 'ses_1' };
});
vi.mock('../../opscenter/lib/active-terminal', () => ({ activeTerminalSessionId: () => 'ses_1', activeTerminalSlot: () => 'terminal:@primary' }));
vi.mock('../../opscenter/cells/registry', async () => {
  const { ScopeProbe } = await import('./test-support.svelte');
  return { entryFor: () => ({ component: ScopeProbe }) };
});

import { railStores } from './rail-store.svelte';
import { railSlideout } from './slideout.svelte';
import { RAIL_FIELD, RAIL_SPECS, type RailEdge } from './rail-model';
import { lastUsedKey } from './rail-open';
import { layoutEditor } from '../../opscenter/layout-editor/editor.svelte';
import { beginDrawerCarry } from '../../opscenter/layout-editor/drawer-carry';
import type { LayoutStore } from '../../opscenter/engine/layout.svelte';
import { BOTTOM_FIELD, box, follow, keyIn, layOutRails, mountRails, ptr, sectionKeysIn, unmountRails, written } from './rail-test-harness';

const source = (file: string): string => readFileSync(join(process.cwd(), 'src', file), 'utf8');
const items = (...widgets: string[]) => ({ items: widgets.map((widget) => ({ widget })) });
const split = (ratio: number, first: string[], second: string[]) => ({ v: 2, ratio, sections: [items(...first), items(...second)] });
const rail = (edge: RailEdge): HTMLElement => document.getElementById(RAIL_SPECS[edge].id)!;
const hairline = (edge: RailEdge): HTMLElement | null => rail(edge).querySelector<HTMLElement>('[data-rail-split]');
const panel = (): HTMLElement | null => document.querySelector<HTMLElement>('[data-rail-slideout]');
const shownWidgets = (): string[] => [...document.querySelectorAll<HTMLElement>('[data-rail-out-section]')].map((s) => s.dataset['railOutWidget']!);
const divider = (): HTMLElement => document.querySelector<HTMLElement>('[data-split-divider]')!;

function carryKey(edge: RailEdge, id: string, from: [number, number], to: [number, number]): void {
  const handle = keyIn(edge, id);
  handle.dispatchEvent(ptr('pointerdown', ...from));
  handle.dispatchEvent(ptr('pointermove', from[0] - 20, from[1] - 20));
  flushSync();
  layOutRails();
  handle.dispatchEvent(ptr('pointermove', ...to));
  flushSync();
  handle.dispatchEvent(ptr('pointerup', ...to));
  flushSync();
}

beforeEach(() => { mountRails(); follow(BOTTOM_FIELD, { v: 1, items: [] }); });
afterEach(() => unmountRails());

describe('splitting', () => {
  test('a key dropped on the bottom band of the side rail becomes the second section; on the top band, the first', () => {
    layoutEditor.active = true;
    flushSync();
    layOutRails();
    expect(document.querySelector('[data-rail-bands]')).toBeNull();
    carryKey('side', 'core.notes', [1018, 52], [800, 380]);
    expect(sectionKeysIn('side')).toEqual([['core.files', 'core.bookmarks'], ['core.notes']]);
    expect(written.at(-1)).toEqual({ field: RAIL_FIELD, value: split(0.5, ['core.files', 'core.bookmarks'], ['core.notes']) });
    expect(document.querySelector('[data-rail-bands]')).toBeNull();
  });

  test('the bands show while a widget is carried and mark the one under the pointer; a drawer card lands as a new section', () => {
    layoutEditor.active = true;
    flushSync();
    layOutRails();
    const card = document.createElement('div');
    document.body.appendChild(card);
    const landed: unknown[] = [];
    const none = { refusal: '', moves: null };
    beginDrawerCarry(card, ptr('pointerdown', 300, 300), { surface: null, zone: none, glance: none, rail: none }, { drag: { target: null }, clearDrag: () => {} } as unknown as LayoutStore, 'terminal', null, {
      onMove: () => {},
      onDrop: (target) => { landed.push(target); },
      onRefuse: () => {},
      onEnd: () => {},
    });
    card.dispatchEvent(ptr('pointermove', 320, 320));
    flushSync();
    expect([...document.querySelectorAll<HTMLElement>('[data-rail-band]')].map((b) => b.dataset['railBand'])).toEqual(['start', 'end']);
    layOutRails();
    card.dispatchEvent(ptr('pointermove', 800, 20));
    flushSync();
    expect(document.querySelector<HTMLElement>('[data-rail-band="start"]')!.dataset['aimed']).toBe('true');
    card.dispatchEvent(ptr('pointerup', 800, 20));
    expect(landed).toEqual([{ area: 'rail', edge: 'side', spot: { section: 0, index: 0, split: 'start' }, moves: null }]);
    card.remove();
  });
});

describe('unsplitting', () => {
  test('dragging the last widget out of a section removes the split, whether it is taken out or moved across', () => {
    follow(RAIL_FIELD, split(0.4, ['core.changes'], ['core.files', 'core.notes']));
    layoutEditor.active = true;
    flushSync();
    layOutRails();
    carryKey('side', 'core.changes', [1018, 20], [1018, 390]);
    expect(sectionKeysIn('side')).toEqual([['core.files', 'core.notes', 'core.changes']]);
    expect(hairline('side')).toBeNull();
    expect(written.at(-1)!.value).toEqual({ v: 2, sections: [items('core.files', 'core.notes', 'core.changes')] });

    follow(RAIL_FIELD, split(0.4, ['core.changes'], ['core.files']));
    layOutRails();
    carryKey('side', 'core.files', [1018, 180], [500, 200]);
    expect(sectionKeysIn('side')).toEqual([['core.changes']]);
    expect(written.at(-1)!.value).toEqual({ v: 2, sections: [items('core.changes')] });
  });
});

describe('the closed rail', () => {
  test('each section lines up from the start of its share, and the hairline sits at the ratio the open divider uses', () => {
    follow(RAIL_FIELD, split(0.3, ['core.changes'], ['core.files', 'core.notes']));
    const sections = rail('side').querySelectorAll<HTMLElement>('[data-rail-section]');
    expect([sections[0]!.style.top, sections[0]!.style.bottom]).toEqual(['0px', 'calc(70%)']);
    expect([sections[1]!.style.top, sections[1]!.style.bottom]).toEqual(['30%', '0px']);
    expect(hairline('side')!.dataset['railSplit']).toBe('30%');
    expect(hairline('side')!.style.top).toBe('30%');
    keyIn('side', 'core.files').click();
    flushSync();
    expect(divider().dataset['splitAt']).toBe('30%');
    expect(document.querySelector<HTMLElement>('[data-rail-out-section="1"]')!.getAttribute('style')).toBe(sections[1]!.getAttribute('style'));
  });

  test('a section with too many keys scrolls its own strip and never moves the line', () => {
    const many = Array.from({ length: 30 }, (_, i) => `row:${i}`);
    follow(RAIL_FIELD, { v: 2, ratio: 0.5, sections: [items('core.changes'), { items: many.map((target) => ({ widget: 'core.terminal', target })) }] });
    expect(sectionKeysIn('side')[1]).toHaveLength(30);
    expect(hairline('side')!.style.top).toBe('50%');
    const css = source('lib/session-rail/SessionRail.svelte');
    const keys = source('lib/zone-shell/ZoneKeys.svelte');
    expect(keys).toMatch(/\.rail__keys \{[^}]*position: absolute;[^}]*overflow-y: auto;/);
    expect(keys).toMatch(/\[data-axis='x'\] \.rail__keys \{[^}]*overflow-x: auto;/);
    expect(css).toMatch(/\.rail \{[^}]*width: var\(--rail-track, var\(--rail-w, 36px\)\);/);
  });
});

describe('opening a split rail', () => {
  test('the clicked widget in its section, the other section first widget, then its last-used one', () => {
    follow(RAIL_FIELD, split(0.5, ['core.changes', 'core.notes'], ['core.files', 'core.task-manager']));
    keyIn('side', 'core.files').click();
    flushSync();
    expect(shownWidgets()).toEqual(['core.changes', 'core.files']);
    keyIn('side', 'core.notes').click();
    flushSync();
    expect(shownWidgets()).toEqual(['core.notes', 'core.files']);
    railSlideout.close();
    flushSync();
    expect(railSlideout.shown('side')).toEqual([]);
    keyIn('side', 'core.task-manager').click();
    flushSync();
    expect(shownWidgets()).toEqual(['core.notes', 'core.task-manager']);
    expect(JSON.parse(localStorage.getItem(lastUsedKey('side'))!)).toEqual(['core.notes', 'core.task-manager']);
  });

  test('open, another key swaps only its own section and the other stays', () => {
    follow(RAIL_FIELD, split(0.5, ['core.changes', 'core.notes'], ['core.files', 'core.task-manager']));
    keyIn('side', 'core.changes').click();
    flushSync();
    expect(shownWidgets()).toEqual(['core.changes', 'core.files']);
    keyIn('side', 'core.task-manager').click();
    flushSync();
    expect(shownWidgets()).toEqual(['core.changes', 'core.task-manager']);
    expect(keyIn('side', 'core.changes').getAttribute('aria-expanded')).toBe('true');
    expect(keyIn('side', 'core.task-manager').getAttribute('aria-expanded')).toBe('true');
    expect(keyIn('side', 'core.files').getAttribute('aria-expanded')).toBe('false');
  });

  test('clicking either open widget closes the whole slide-out', () => {
    follow(RAIL_FIELD, split(0.5, ['core.changes', 'core.notes'], ['core.files']));
    keyIn('side', 'core.notes').click();
    flushSync();
    keyIn('side', 'core.files').click();
    flushSync();
    expect(railSlideout.shown('side')).toEqual([]);
    expect(keyIn('side', 'core.notes').getAttribute('aria-expanded')).toBe('false');
    keyIn('side', 'core.files').click();
    flushSync();
    expect(railSlideout.shown('side')).toEqual(['core.notes', 'core.files']);
    keyIn('side', 'core.notes').click();
    flushSync();
    expect(railSlideout.shown('side')).toEqual([]);
  });

  test('both sections share the one width the edge handle resizes', () => {
    follow(RAIL_FIELD, split(0.5, ['core.changes'], ['core.files']));
    keyIn('side', 'core.changes').click();
    flushSync();
    expect(document.querySelectorAll('[data-rail-slideout] [data-rail-grip]')).toHaveLength(1);
    expect(panel()!.style.width).toBe('380px');
    expect(source('lib/session-rail/RailSlideout.svelte')).toMatch(/\.rail-out__section \{[^}]*position: absolute;/);
  });
});

describe('the divider', () => {
  test('a pointer drag moves the line live and saves once at the end; the closed rail hairline follows', () => {
    follow(RAIL_FIELD, split(0.5, ['core.changes'], ['core.files']));
    keyIn('side', 'core.changes').click();
    flushSync();
    panel()!.getBoundingClientRect = () => box(620, 0, 380, 400);
    const before = written.length;
    divider().dispatchEvent(ptr('pointerdown', 800, 200));
    divider().dispatchEvent(ptr('pointermove', 800, 100));
    flushSync();
    expect(hairline('side')!.style.top).toBe('25%');
    expect(divider().getAttribute('aria-valuenow')).toBe('25');
    expect(written.length).toBe(before);
    divider().dispatchEvent(ptr('pointerup', 800, 100));
    flushSync();
    expect(written.slice(before)).toEqual([{ field: RAIL_FIELD, value: split(0.25, ['core.changes'], ['core.files']) }]);
  });

  test('from the keyboard: the arrows step it and save, Home puts it back', () => {
    follow(RAIL_FIELD, split(0.5, ['core.changes'], ['core.files']));
    keyIn('side', 'core.changes').click();
    flushSync();
    divider().dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true }));
    flushSync();
    expect(hairline('side')!.style.top).toBe('52%');
    expect(written.at(-1)!.value).toEqual(split(0.52, ['core.changes'], ['core.files']));
    divider().dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowUp', bubbles: true }));
    divider().dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowUp', bubbles: true }));
    flushSync();
    expect(railStores.side.ratio).toBe(0.48);
    divider().dispatchEvent(new KeyboardEvent('keydown', { key: 'Home', bubbles: true }));
    flushSync();
    expect(railStores.side.ratio).toBe(0.5);
    expect(divider().getAttribute('role')).toBe('separator');
    expect(divider().getAttribute('aria-orientation')).toBe('horizontal');
  });
});

describe('the old flat value', () => {
  test('a stored v1 list draws as one section with every widget, and the first edit saves the v2 shape', () => {
    follow(RAIL_FIELD, { v: 1, items: [{ widget: 'core.notes' }, { widget: 'core.files' }, { widget: 'core.task-manager' }] });
    expect(sectionKeysIn('side')).toEqual([['core.notes', 'core.files', 'core.task-manager']]);
    expect(hairline('side')).toBeNull();
    expect(written).toEqual([]);
    layoutEditor.active = true;
    flushSync();
    keyIn('side', 'core.task-manager').dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowUp', bubbles: true }));
    flushSync();
    expect(written.at(-1)).toEqual({ field: RAIL_FIELD, value: { v: 2, sections: [items('core.notes', 'core.task-manager', 'core.files')] } });
  });
});

describe('the bottom rail mirror', () => {
  test('left and right bands, a vertical hairline at the ratio, sections side by side, the divider on the left and right arrows', () => {
    follow(BOTTOM_FIELD, { v: 1, items: [{ widget: 'core.notes' }, { widget: 'core.ledger' }] });
    layoutEditor.active = true;
    flushSync();
    layOutRails();
    carryKey('bottom', 'core.ledger', [56, 718], [850, 600]);
    expect(sectionKeysIn('bottom')).toEqual([['core.notes'], ['core.ledger']]);
    expect(written.at(-1)).toEqual({ field: BOTTOM_FIELD, value: split(0.5, ['core.notes'], ['core.ledger']) });
    expect(hairline('bottom')!.style.left).toBe('50%');
    const second = rail('bottom').querySelectorAll<HTMLElement>('[data-rail-section]')[1]!;
    expect([second.style.left, second.style.right]).toEqual(['50%', '0px']);

    layoutEditor.active = false;
    flushSync();
    keyIn('bottom', 'core.ledger').click();
    flushSync();
    expect(shownWidgets()).toEqual(['core.notes', 'core.ledger']);
    expect(panel()!.style.height).toBe('320px');
    expect(divider().dataset['splitDivider']).toBe('x');
    divider().dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }));
    flushSync();
    expect(hairline('bottom')!.style.left).toBe('52%');
    expect(written.at(-1)!.field).toBe(BOTTOM_FIELD);
  });
});
