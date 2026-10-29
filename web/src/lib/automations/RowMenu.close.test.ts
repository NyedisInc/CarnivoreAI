/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import Host from './fixtures/RowMenuHost.svelte';
import { setLocale } from '../i18n/index.svelte';
import { installPopoverPolyfill } from '../popover-jsdom-polyfill';

installPopoverPolyfill();
setLocale('en');

let app: ReturnType<typeof mount> | null = null;
let errors: unknown[] = [];
const onError = (e: ErrorEvent) => errors.push(e.error ?? e.message);
const onReject = (e: PromiseRejectionEvent) => errors.push(e.reason);
let consoleError: ReturnType<typeof vi.spyOn>;
const onPick = vi.fn();

beforeEach(() => {
  errors = [];
  consoleError = vi.spyOn(console, 'error').mockImplementation(() => {});
  window.addEventListener('error', onError);
  window.addEventListener('unhandledrejection', onReject);
  const target = document.createElement('div');
  document.body.append(target);
  app = mount(Host, { target, props: { onPick } });
  flushSync();
});

afterEach(async () => {
  window.removeEventListener('error', onError);
  window.removeEventListener('unhandledrejection', onReject);
  if (app) await unmount(app);
  app = null;
  document.body.replaceChildren();
  consoleError.mockRestore();
  onPick.mockReset();
});

function open(): HTMLElement {
  const kebab = document.querySelector<HTMLElement>('[data-kebab]')!;
  kebab.click();
  flushSync();
  expect(document.querySelector('[data-node="edit"]')).not.toBeNull();
  return kebab;
}

async function expectQuiet(): Promise<void> {
  await new Promise((r) => setTimeout(r, 0));
  flushSync();
  expect(errors.map((e) => (e as Error)?.stack ?? String(e))).toEqual([]);
  expect(consoleError).not.toHaveBeenCalled();
}

test('Escape closes the menu with no error and gives focus back to the kebab', async () => {
  const kebab = open();
  expect(() => {
    document.activeElement?.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    flushSync();
  }).not.toThrow();
  await expectQuiet();
  expect(document.querySelector('[data-node="edit"]')).toBeNull();
  expect(document.activeElement).toBe(kebab);
});

test('a press outside closes the menu with no error', async () => {
  open();
  const outside = document.querySelector<HTMLElement>('[data-outside]')!;
  expect(() => {
    outside.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true }));
    outside.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
    flushSync();
  }).not.toThrow();
  await expectQuiet();
  expect(document.querySelector('[data-node="edit"]')).toBeNull();
});

test('choosing an item picks it and closes with no error', async () => {
  open();
  expect(() => {
    document.querySelector<HTMLElement>('[data-node="duplicate"]')!.click();
    flushSync();
  }).not.toThrow();
  await expectQuiet();
  expect(onPick).toHaveBeenCalledWith('duplicate');
});
