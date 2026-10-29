/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

vi.mock('../opscenter/api', () => ({
  auth: { state: 'signed-in' },
  initAuth: () => {},
  startEvents: () => {},
}));

const marker = (html: string) =>
  ((anchor: Comment) => {
    const holder = document.createElement('span');
    holder.innerHTML = html;
    anchor.before(holder);
  }) as never;

vi.mock('../lib/dynamic-tabs/popout-tabs', () => ({
  popoutTab: (id: string) =>
    id === 'fixture'
      ? { id, labelKey: 'opscenter.popout.title', popout: true, body: { component: marker('<i data-fixture-body></i>'), titleKey: 'opscenter.popout.title', titleActions: marker('<b data-fixture-action></b>') } }
      : null,
}));

import TabPopout from './TabPopout.svelte';

let app: ReturnType<typeof mount> | null = null;

beforeEach(() => {
  (globalThis as { ResizeObserver?: unknown }).ResizeObserver = class {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
  };
});

afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
});

test('the title and the tab\'s own title actions sit in the one title strip, with no icon menu and no close', () => {
  const target = document.createElement('div');
  document.body.append(target);
  app = mount(TabPopout, { target, props: { tab: 'fixture' } });
  flushSync();
  const strip = target.querySelector('[data-widget-head]');
  expect(strip, 'the one widget title strip').not.toBeNull();
  expect(strip!.querySelector('.oc-frame-name')?.textContent?.trim()).not.toBe('');
  expect(strip!.querySelector('[data-fixture-action]'), 'the tab\'s title actions are in the strip').not.toBeNull();
  expect(strip!.querySelector('[data-corner]')).toBeNull();
  expect(strip!.querySelector('[data-head-close]')).toBeNull();
  expect(target.querySelector('[data-fixture-body]')).not.toBeNull();
});
