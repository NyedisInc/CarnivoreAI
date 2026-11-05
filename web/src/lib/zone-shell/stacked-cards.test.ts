/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { flushSync, mount, unmount } from 'svelte';

vi.mock('../../opscenter/api', async (importOriginal) => {
  const real = await importOriginal<Record<string, unknown>>();
  return { ...real, ledger: { status: 'ok', data: null, fetchedAt: null, error: null }, primarySessionId: () => '' };
});

import DrawerZone from '../drawer-zone/DrawerZone.svelte';
import { drawerZone } from '../drawer-zone/zone-store.svelte';
import { layoutEditor } from '../../opscenter/layout-editor/editor.svelte';
import { installPopoverPolyfill } from '../popover-jsdom-polyfill';

installPopoverPolyfill();

let host: HTMLElement;
let instance: object | null = null;
let sheet: HTMLStyleElement;

const TOKENS: Readonly<Record<string, string>> = {
  '--oc-space-2': '8px',
  '--oc-space-1': '4px',
  '--oc-space-1-5': '6px',
  '--oc-border': '1px',
};

function shippedCss(file: string, phone: boolean): string {
  const source = readFileSync(join(__dirname, '..', file), 'utf8');
  let css = /<style>([\s\S]*)<\/style>/.exec(source)![1]!;
  css = css.replace(/@layer components\s*{/, '').replace(/}\s*$/, '').replace(/:global\(([^)]*)\)/g, '$1');
  css = phone ? css.replace(/@media \(max-width: 640px\)\s*{([\s\S]*?\n {4}})\s*}/, '$1') : css.replace(/@media \(max-width: 640px\)\s*{[\s\S]*?\n {4}}\s*}/, '');
  for (const [name, value] of Object.entries(TOKENS)) css = css.split(`var(${name})`).join(value);
  return css;
}

function mountStack(widgets: string[], phone: boolean, editing: boolean): HTMLElement[] {
  const stored = { v: 1, items: widgets.map((widget) => ({ widget })) };
  (globalThis as { PreferenceBridge?: unknown }).PreferenceBridge = {
    read: () => stored,
    write: async () => ({ status: 'committed' }),
    follow: () => () => {},
  };
  drawerZone.reload();
  layoutEditor.active = editing;
  sheet = document.createElement('style');
  sheet.textContent = ['zone-shell/PlacementBody.svelte', 'ledger-drawer/DrawerLedger.svelte', 'drawer-zone/ZoneItem.svelte']
    .map((file) => shippedCss(file, phone))
    .join('\n');
  document.head.appendChild(sheet);
  host = document.createElement('div');
  document.body.appendChild(host);
  instance = mount(DrawerZone, { target: host });
  flushSync();
  return [...host.querySelectorAll<HTMLElement>('[data-zone-card]')];
}

beforeEach(() => {
  (globalThis as { ResizeObserver?: unknown }).ResizeObserver = class {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
  };
});

afterEach(() => {
  if (instance) unmount(instance as never);
  instance = null;
  layoutEditor.active = false;
  sheet.remove();
  document.body.replaceChildren();
  delete (globalThis as { PreferenceBridge?: unknown }).PreferenceBridge;
});

const drawn = (width: string): boolean => !['0', '0px'].includes(width);
const px = (v: string): number => (v === '' ? 0 : parseFloat(v) || 0);

function seam(a: Element, b: Element): { lines: number; gap: number } {
  const first = getComputedStyle(a);
  const second = getComputedStyle(b);
  return {
    lines: Number(drawn(first.borderBottomWidth)) + Number(drawn(second.borderTopWidth)),
    gap: px(first.marginBottom) + px(second.marginTop),
  };
}

const ORDINARY = ['core.notes', 'core.activity-log', 'core.files'];

describe.each([
  ['three ordinary cards', ORDINARY, false],
  ['the usage card above an ordinary one', ['core.ledger', 'core.notes', 'core.files'], false],
  ['the usage card below an ordinary one', ['core.notes', 'core.ledger', 'core.files'], false],
  ['the usage card between two ordinary ones, on a phone', ['core.notes', 'core.ledger', 'core.files'], true],
  ['the usage card last, on a phone', ['core.notes', 'core.files', 'core.ledger'], true],
] as const)('%s', (_name, widgets, phone) => {
  test('one hairline and no gap between neighbours; the outer edges of the stack are untouched', () => {
    const cards = mountStack([...widgets], phone, false);
    expect(cards.length).toBe(3);
    for (let at = 0; at < cards.length - 1; at += 1) {
      expect(seam(cards[at]!, cards[at + 1]!)).toEqual({ lines: 1, gap: 0 });
    }
    expect(drawn(getComputedStyle(cards[0]!).borderTopWidth)).toBe(true);
    expect(drawn(getComputedStyle(cards[2]!).borderBottomWidth)).toBe(true);
  });
});

describe('edit layout', () => {
  test.each([[ORDINARY], [['core.ledger', 'core.notes', 'core.files']]])('every card starts the same way: the strip above it separates them', (widgets) => {
    const cards = mountStack([...widgets], false, true);
    expect(cards.length).toBe(3);
    const tops = cards.map((card) => `${getComputedStyle(card).marginTop}|${drawn(getComputedStyle(card).borderTopWidth)}`);
    expect(new Set(tops).size).toBe(1);
    expect(host.querySelectorAll('.dz-strip').length).toBe(3);
    expect(drawn(getComputedStyle(cards[0]!).borderTopWidth)).toBe(true);
  });
});
