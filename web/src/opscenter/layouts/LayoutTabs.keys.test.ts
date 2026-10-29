/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

const saved = vi.hoisted(() => [
  { layout_uuid: 'a', name: 'alpha', colour: 'cyan', gradient: null },
  { layout_uuid: 'b', name: 'bravo', colour: '', gradient: null },
  { layout_uuid: 'c', name: 'charlie', colour: '', gradient: 'ember' },
]);
vi.mock('../../lib/layouts-bridge/api.svelte', () => ({
  layouts: { data: saved },
  layoutByUuid: (uuid: string) => saved.find((one) => one.layout_uuid === uuid) ?? null,
}));

import LayoutTabs from './LayoutTabs.svelte';
import { layoutMode } from './mode.svelte';
import { setTabs } from './layout-tabs.svelte';

let instance: ReturnType<typeof mount> | null = null;
const opened: string[] = [];
const tab = (uuid: string): HTMLElement => document.querySelector<HTMLElement>(`[data-tab="${uuid}"]`)!;

function press(key: string): void {
  (document.activeElement as HTMLElement).dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true }));
  flushSync();
}

beforeEach(() => {
  (globalThis as { CloudeWeb?: unknown }).CloudeWeb = { layoutPage: { openLayout: (uuid: string) => opened.push(uuid) } };
  layoutMode.uuid = 'a';
  layoutMode.name = 'alpha';
  setTabs(['a', 'b', 'c']);
  const host = document.createElement('div');
  document.body.append(host);
  instance = mount(LayoutTabs, { target: host });
  flushSync();
});

afterEach(() => {
  if (instance) unmount(instance);
  instance = null;
  opened.length = 0;
  document.body.replaceChildren();
});

test('the tabs are the tab strip: one tablist, a tab per Layout, the open one selected and the one Tab stop', () => {
  const tabs = [...document.querySelectorAll<HTMLElement>('[role="tablist"] [role="tab"]')];
  expect(tabs.map((one) => one.textContent?.trim())).toEqual(['alpha', 'bravo', 'charlie']);
  expect(tabs.map((one) => one.getAttribute('aria-selected'))).toEqual(['true', 'false', 'false']);
  expect(tabs.filter((one) => one.tabIndex === 0)).toEqual([tab('a')]);
  expect(tab('a').querySelector<HTMLElement>('.oc-tab-name')!.getAttribute('style'), 'each name wears its Layout colour').toContain('--drawer-hue-cyan');
  expect(document.querySelector('.oc-tab-icon--action'), 'a Layout tab has no component icon').toBeNull();
});

test('the arrows, Home and End move focus between the Layout tabs, wrapping, and focus opens nothing', () => {
  tab('a').focus();
  press('ArrowRight');
  expect(document.activeElement).toBe(tab('b'));
  press('End');
  expect(document.activeElement).toBe(tab('c'));
  press('ArrowRight');
  expect(document.activeElement, 'wraps to the first').toBe(tab('a'));
  press('ArrowLeft');
  expect(document.activeElement, 'wraps to the last').toBe(tab('c'));
  press('Home');
  expect(document.activeElement).toBe(tab('a'));
  expect(opened, 'moving focus opens no Layout').toEqual([]);
  tab('b').click();
  expect(opened).toEqual(['b']);
});
