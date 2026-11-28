/** @vitest-environment jsdom */
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { afterEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

vi.mock('../item-settings/store.svelte', () => ({ widgetSetting: () => true, isWidgetDisabled: () => false }));
vi.mock('../../opscenter/lib/active-terminal', () => ({ activeTerminalSessionId: () => 'ses_1', activeTerminalSlot: () => 'terminal:@primary' }));

import KeysHarness from './fixtures/KeysHarness.svelte';

let handle: ReturnType<typeof mount> | null = null;
afterEach(() => {
  if (handle) unmount(handle);
  handle = null;
  document.body.innerHTML = '';
});

test('a seam arrow key steps the cut through oncut and saves once', () => {
  const steps: Array<[number, number]> = [];
  handle = mount(KeysHarness, { target: document.body, props: { cuts: [0.5], oncut: (i: number, v: number) => steps.push([i, v]) } });
  flushSync();
  const divider = document.querySelector<HTMLElement>('[data-split-divider="y"]');
  expect(divider).not.toBeNull();
  divider!.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true, cancelable: true }));
  expect(steps).toHaveLength(1);
  expect(steps[0]![0]).toBe(0);
  expect(steps[0]![1]).toBeGreaterThan(0.5);
  expect((handle as unknown as { saved: boolean[] }).saved).toHaveLength(1);
});

test('edit layout keeps the seam a plain hairline, so carried keys are not fought by a handle', () => {
  handle = mount(KeysHarness, { target: document.body, props: { cuts: [0.5], editing: true, oncut: () => {} } });
  flushSync();
  expect(document.querySelector('[data-split-divider]')).toBeNull();
  expect(document.querySelector('.rail__split')).not.toBeNull();
});

test('every seam line is the drawer edge line token, never its own number', () => {
  const tokens = readFileSync(join(process.cwd(), 'src/opscenter/tokens.css'), 'utf8');
  expect(tokens).toContain('--oc-section-line: var(--oc-grip-line);');
  const keys = readFileSync(join(process.cwd(), 'src/lib/zone-shell/ZoneKeys.svelte'), 'utf8');
  expect(keys).not.toMatch(/\.rail__split \{[^}]*(?:height|width): 2px/);
});

test('a lower section starts after half the seam line, so its head has the full even height', () => {
  const out = readFileSync(join(process.cwd(), 'src/lib/session-rail/RailSlideout.svelte'), 'utf8');
  expect(out).toContain('.rail-out--side .rail-out__section[data-seam-before] {\n      margin-top: calc(var(--oc-section-line) / 2);');
  expect(out).toContain('.rail-out--bottom .rail-out__section[data-seam-before] {\n      margin-left: calc(var(--oc-section-line) / 2);');
});
