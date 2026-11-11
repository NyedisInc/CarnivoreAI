/** @vitest-environment jsdom */
import { afterEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import LayoutCommandBar from './LayoutCommandBar.svelte';
import { layoutMode } from './mode.svelte';
import { viewport } from '../engine/viewport.svelte';
import { closeWidgetDrawer, surfaceDrawer } from '../layout-editor/editor.svelte';

vi.stubGlobal('ResizeObserver', class { observe(): void {} disconnect(): void {} unobserve(): void {} });

const mounted: ReturnType<typeof mount>[] = [];
afterEach(async () => {
  for (const component of mounted.splice(0)) await unmount(component);
  document.body.replaceChildren();
  layoutMode.uuid = '';
  layoutMode.members = [];
  closeWidgetDrawer();
  viewport.wide = true;
});

function open(): HTMLElement {
  layoutMode.uuid = 'L1';
  layoutMode.name = 'work';
  layoutMode.members = [];
  const host = document.createElement('div');
  document.body.append(host);
  mounted.push(mount(LayoutCommandBar, { target: host }));
  flushSync();
  return host;
}

test('wide: the button is the last item and toggles the terminal drawer', () => {
  viewport.wide = true;
  const host = open();
  const button = host.querySelector('[data-bar-tool="add-widgets"]') as HTMLButtonElement;
  expect(button.textContent?.trim()).toBe('add widgets');
  expect(host.querySelector('section')!.lastElementChild).toBe(button);
  expect(button.getAttribute('aria-pressed')).toBe('false');
  button.click();
  flushSync();
  expect(surfaceDrawer.surface).toBe('terminal');
  expect(button.getAttribute('aria-pressed')).toBe('true');
  button.click();
  flushSync();
  expect(surfaceDrawer.surface).toBeNull();
});

test('narrow: no button', () => {
  viewport.wide = false;
  expect(open().querySelector('[data-bar-tool="add-widgets"]')).toBeNull();
});
