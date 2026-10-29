/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test } from 'vitest';
import { flushSync } from 'svelte';
import { RAIL_FIELD } from './rail-model';
import { layoutEditor } from '../../opscenter/layout-editor/editor.svelte';
import { follow, keyIn, mountRails, unmountRails, written } from './rail-test-harness';
import { setLocale } from '../i18n/index.svelte';
import { PREFERENCE_FIELD } from '../sidebar-widgets/rail-icons.svelte';

setLocale('en');

const strip = (): HTMLElement => document.querySelector<HTMLElement>('[data-session-rail][data-rail-edge="side"]')!;
const has = (key: string): boolean => [...strip().querySelectorAll<HTMLElement>('[data-zone-item]')].some((el) => el.dataset['zoneItem'] === key);

beforeEach(() => {
  mountRails();
  follow(RAIL_FIELD, { v: 2, sections: [{ items: [{ widget: 'core.notes' }, { widget: 'core.files' }] }] });
  follow(PREFERENCE_FIELD, ['core.files']);
  flushSync();
});
afterEach(() => {
  layoutEditor.active = false;
  unmountRails();
});

test('a hidden key is gone outside edit layout and nothing wears a badge', () => {
  expect(has('core.notes')).toBe(true);
  expect(has('core.files')).toBe(false);
  expect(strip().querySelector('[data-edit-badge]')).toBeNull();
});

test('edit layout draws every key with a dashed cell and a badge; the hidden one is dimmed; the badge shows it again', () => {
  layoutEditor.active = true;
  flushSync();
  expect(has('core.files')).toBe(true);
  expect(strip().querySelectorAll('[data-edit-cell] [data-edit-badge]')).toHaveLength(2);
  const cell = keyIn('side', 'core.files').closest<HTMLElement>('[data-edit-cell]')!;
  expect(cell.hasAttribute('data-hidden')).toBe(true);
  cell.querySelector<HTMLButtonElement>('[data-edit-badge]')!.click();
  flushSync();
  expect(JSON.stringify(written.at(-1))).toContain(PREFERENCE_FIELD);
});
