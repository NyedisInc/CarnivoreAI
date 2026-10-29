/** @vitest-environment jsdom */
import { afterEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import DuplicatePrompt from './DuplicatePrompt.svelte';
import { askDuplicate, closeDuplicate, duplicateKind, duplicatePrompt, type DuplicateFacts } from './duplicate-prompt.svelte';
import type { DropTarget } from '../engine/layout.svelte';
import { installPopoverPolyfill } from '../../lib/popover-jsdom-polyfill';
import { setLocale } from '../../lib/i18n/index.svelte';

installPopoverPolyfill();
setLocale('en');

const one: DuplicateFacts = { family: false, onScreen: false, inGlance: null, repeatable: false };
const surface = { area: 'surface' as const, target: {} as DropTarget };

test('which drops ask, and which question', () => {
  expect(duplicateKind(surface, one)).toBeNull();
  expect(duplicateKind({ area: 'zone', index: 0, moves: null }, one)).toBeNull();
  expect(duplicateKind({ area: 'glance', index: 0, moves: null }, one)).toBeNull();
  expect(duplicateKind(surface, { ...one, onScreen: true })).toBe('one');
  expect(duplicateKind({ area: 'zone', index: 0, moves: 'core.notes' }, one)).toBe('one');
  expect(duplicateKind({ area: 'glance', index: 0, moves: 'g-1' }, one)).toBe('one');
  expect(duplicateKind({ area: 'glance', index: 0, moves: null }, { ...one, repeatable: true, inGlance: 'g-1' })).toBe('copy');
  expect(duplicateKind({ area: 'zone', index: 0, moves: null }, { ...one, onScreen: true })).toBeNull();
  expect(duplicateKind(surface, { ...one, family: true, onScreen: true })).toBeNull();
});

let app: ReturnType<typeof mount> | null = null;
afterEach(() => {
  if (app) unmount(app);
  app = null;
  closeDuplicate();
  document.body.replaceChildren();
});

function draw(): void {
  app = mount(DuplicatePrompt, { target: document.body });
  flushSync();
}

test('"copy" offers add copy, move here and cancel; each answer runs once and takes the prompt down', () => {
  const onCopy = vi.fn();
  const onMove = vi.fn();
  draw();
  askDuplicate({ kind: 'copy', title: 'providers', x: 10, y: 10, onCopy, onMove });
  flushSync();
  const card = document.querySelector<HTMLElement>('[data-duplicate-prompt="copy"]')!;
  expect(card.textContent).toContain('providers is already here. add a second copy?');
  expect(document.activeElement, 'the confirming answer takes focus').toBe(card.querySelector('[data-dupe-copy]'));
  card.querySelector<HTMLElement>('[data-dupe-copy]')!.click();
  flushSync();
  expect(onCopy).toHaveBeenCalledTimes(1);
  expect(onMove).not.toHaveBeenCalled();
  expect(duplicatePrompt.ask).toBeNull();
  expect(document.querySelector('[data-duplicate-prompt]')).toBeNull();
});

test('"one" says it can only be in one place and offers move here; Escape cancels without acting', () => {
  const onMove = vi.fn();
  draw();
  askDuplicate({ kind: 'one', title: 'notes', x: 10, y: 10, onMove });
  flushSync();
  const card = document.querySelector<HTMLElement>('[data-duplicate-prompt="one"]')!;
  expect(card.textContent).toContain('only be in one place');
  expect(card.querySelector('[data-dupe-copy]')).toBeNull();
  card.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
  flushSync();
  expect(onMove).not.toHaveBeenCalled();
  expect(document.querySelector('[data-duplicate-prompt]')).toBeNull();
});
