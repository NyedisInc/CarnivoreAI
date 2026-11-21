/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

import CascadeMenu from './CascadeMenu.svelte';
import { setLocale } from '../i18n/index.svelte';
import { installPopoverPolyfill } from '../popover-jsdom-polyfill';
import { closeOpenMenu } from './open-menu';
import type { MenuNode } from './add-component-menu';

installPopoverPolyfill();
setLocale('en');

let menu: { anchor: HTMLElement } | null = null;
let app: ReturnType<typeof mount> | null = null;
let errors: unknown[] = [];
const onPick = vi.fn<(id: string) => void>();
const onError = (e: ErrorEvent): void => void errors.push(e.error ?? e.message);
const onReject = (e: PromiseRejectionEvent): void => void errors.push(e.reason);

const NODES: MenuNode[] = ['edit', 'duplicate'].map((id): MenuNode => ({ id, label: id, run: () => onPick(id) }));

beforeEach(() => {
  errors = [];
  window.addEventListener('error', onError);
  window.addEventListener('unhandledrejection', onReject);
});

afterEach(async () => {
  window.removeEventListener('error', onError);
  window.removeEventListener('unhandledrejection', onReject);
  if (app) await unmount(app);
  app = null;
  menu = null;
  closeOpenMenu();
  document.body.replaceChildren();
  onPick.mockReset();
});

function open(): HTMLButtonElement {
  const button = document.createElement('button');
  button.dataset.baseExempt = 'test host, not shipped UI';
  const outside = document.createElement('button');
  outside.dataset.baseExempt = 'test host, not shipped UI';
  outside.dataset.outside = '';
  const target = document.createElement('div');
  document.body.append(button, outside, target);
  menu = { anchor: button };
  app = mount(CascadeMenu, {
    target,
    props: {
      root: NODES,
      get anchor(): HTMLElement {
        return menu!.anchor;
      },
      label: 'menu',
      onClose: () => {
        menu = null;
      },
    },
  });
  flushSync();
  expect(document.querySelector('[data-node="edit"]')).not.toBeNull();
  return button;
}

async function expectClosedQuietly(): Promise<void> {
  await new Promise((r) => setTimeout(r, 0));
  flushSync();
  expect(errors.map((e) => (e instanceof Error ? (e.stack ?? e.message) : String(e)))).toEqual([]);
  expect(menu).toBeNull();
}

test('Escape closes the menu with no error and gives focus back to the button', async () => {
  const button = open();
  expect(() => {
    (document.activeElement ?? document.body).dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    flushSync();
  }).not.toThrow();
  await expectClosedQuietly();
  expect(document.activeElement).toBe(button);
});

test('a press outside closes the menu with no error', async () => {
  open();
  const outside = document.querySelector<HTMLElement>('[data-outside]')!;
  expect(() => {
    outside.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true }));
    flushSync();
  }).not.toThrow();
  await expectClosedQuietly();
});

test('choosing an item runs it with no error (closing after a pick is the caller\'s run, as every caller does)', async () => {
  open();
  expect(() => {
    document.querySelector<HTMLElement>('[data-node="duplicate"]')!.click();
    flushSync();
  }).not.toThrow();
  await new Promise((r) => setTimeout(r, 0));
  expect(errors).toEqual([]);
  expect(onPick).toHaveBeenCalledWith('duplicate');
});
