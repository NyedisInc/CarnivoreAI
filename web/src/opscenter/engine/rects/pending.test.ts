/** @vitest-environment jsdom */
import { afterEach, expect, test } from 'vitest';
import { pendingForTab } from './pending';
import { tabName } from '../tabs-motion/tab-name';
import type { LayoutStore } from '../layout.svelte';

afterEach(() => {
  document.body.innerHTML = '';
});

function storeWithTwoTabs(): LayoutStore {
  const layout = { v: 6, rows: [{ id: 'r1', kind: 'flex', size: 1, slots: [{ id: 'terminal:row:1', fr: 1 }] }], hidden: [], heroCollapsed: false, collapsed: [] };
  return { state: { layout, groups: { 'terminal:row:1': ['terminal:row:1', 'terminal:row:2'] } } } as unknown as LayoutStore;
}

test('the ghost label is the name the strip draws, else the tab id', () => {
  const store = storeWithTwoTabs();
  document.body.innerHTML = '<button data-tab="terminal:row:2"><span class="oc-tab-name"> build box </span></button>';
  expect(pendingForTab(store, 'terminal:row:2')?.ghost?.label).toBe('build box');
  document.body.innerHTML = '<button data-tab="terminal:row:2"><span class="oc-tab-name"></span></button>';
  expect(pendingForTab(store, 'terminal:row:2')?.ghost?.label).toBe('terminal:row:2');
});

test('the strip name function reads the span inside its own track, else the id', () => {
  document.body.innerHTML = '<div id="t"><button data-tab="a"><span class="oc-tab-name">alpha</span></button><button data-tab="b"></button></div>';
  const track = document.getElementById('t')!;
  expect(tabName('a', track)).toBe('alpha');
  expect(tabName('b', track)).toBe('b');
});
