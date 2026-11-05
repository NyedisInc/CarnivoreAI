/** @vitest-environment jsdom */
import { afterEach, expect, test } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import Page from './Page.svelte';
import { viewport } from '../engine/viewport.svelte';

let app: ReturnType<typeof mount> | null = null;
afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.className = '';
  document.body.replaceChildren();
  viewport.narrow = false;
});

function page(onClose?: () => void): void {
  viewport.narrow = true;
  app = mount(Page, { target: document.body, props: { title: 'Plugins', onClose } });
  flushSync();
}

test('the back arrow raises ps-page-back and unmounting clears it', () => {
  page(() => {});
  expect(document.querySelector('[data-page-back]')).not.toBeNull();
  expect(document.body.classList.contains('ps-page-back')).toBe(true);
  unmount(app!);
  app = null;
  expect(document.body.classList.contains('ps-page-back')).toBe(false);
});

test('a page without a back arrow leaves the class off', () => {
  page();
  expect(document.querySelector('[data-page-back]')).toBeNull();
  expect(document.body.classList.contains('ps-page-back')).toBe(false);
});
