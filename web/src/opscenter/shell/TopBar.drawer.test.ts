/** @vitest-environment jsdom */
import fs from 'node:fs';
import path from 'node:path';
import { afterEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

vi.mock('../api', () => ({
  isDemo: () => false,
  sessions: { status: 'idle', data: null },
  transport: { state: 'unknown' },
}));

import TopBar from './TopBar.svelte';

const mounted: ReturnType<typeof mount>[] = [];
afterEach(async () => {
  for (const c of mounted.splice(0)) await unmount(c);
  document.body.replaceChildren();
  delete (globalThis as { SessionSidebar?: unknown }).SessionSidebar;
});

function render(): HTMLElement {
  const target = document.createElement('div');
  document.body.append(target);
  mounted.push(mount(TopBar, { target, props: {} }));
  flushSync();
  return target;
}

test('the reopen button opens the drawer through its own controller', () => {
  const open = vi.fn();
  (globalThis as { SessionSidebar?: unknown }).SessionSidebar = { open };
  const btn = render().querySelector<HTMLButtonElement>('.oc-topbar-drawer');
  expect(btn, 'the reopen control is missing from the home bar').not.toBeNull();
  btn!.click();
  expect(open).toHaveBeenCalledTimes(1);
});

test('NEGATIVE: with no drawer controller loaded, a click throws nothing', () => {
  const btn = render().querySelector<HTMLButtonElement>('.oc-topbar-drawer');
  expect(() => btn!.click()).not.toThrow();
});

test('the button is shown only while the drawer is closed, above phone width', () => {
  const src = fs.readFileSync(path.join(process.cwd(), 'src/lib/zone-shell/TabKey.svelte'), 'utf8');
  expect(src).toMatch(/\.oc-topbar-drawer \{\s*display: none;/);
  expect(src).toMatch(
    /@media \(min-width: 701px\) \{\s*:global\(body:not\(:has\(\.session-sidebar-panel--open\)\)\) \.oc-topbar-drawer \{\s*display: inline-flex;/,
  );
});
