/** @vitest-environment jsdom */
import { afterEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

vi.mock('../api', () => ({
  isDemo: () => false,
  sessions: { status: 'idle', data: null },
  transport: { state: 'unknown' },
}));

import TopBar from './TopBar.svelte';
import { viewport } from '../engine/viewport.svelte';

const OPEN = 'session-sidebar-panel--open';
const g = globalThis as { SessionSidebar?: unknown };

const mounted: ReturnType<typeof mount>[] = [];
afterEach(async () => {
  for (const c of mounted.splice(0)) await unmount(c);
  document.body.replaceChildren();
  delete g.SessionSidebar;
  // Restore the module's own default so an earlier test's width can never
  // leak into a later, unrelated suite that imports the same singleton.
  viewport.wide = true;
  viewport.phone = false;
});

function installDrawer(): { panel: HTMLElement; backdrop: HTMLElement } {
  const panel = document.createElement('aside');
  panel.id = 'session-sidebar-panel';
  panel.innerHTML = '<div class="drawer-tabs" role="tablist"></div>';
  const backdrop = document.createElement('div');
  document.body.append(backdrop, panel);
  const ctl = {
    isOpen: false,
    open() { ctl.isOpen = true; panel.classList.add(OPEN); },
    close() { ctl.isOpen = false; panel.classList.remove(OPEN); },
    toggle() { if (ctl.isOpen) ctl.close(); else ctl.open(); },
  };
  backdrop.addEventListener('click', () => ctl.close());
  g.SessionSidebar = ctl;
  return { panel, backdrop };
}

function render(): HTMLElement {
  const target = document.createElement('div');
  document.body.append(target);
  mounted.push(mount(TopBar, { target, props: {} }));
  flushSync();
  return target;
}

async function settle(): Promise<void> {
  await Promise.resolve();
  flushSync();
}

function phone(): void {
  viewport.wide = false;
  viewport.phone = true;
}

test('phone width: tapping the mark opens the tabbed agents drawer', async () => {
  phone();
  const { panel } = installDrawer();
  const root = render();
  const brand = root.querySelector<HTMLButtonElement>('.oc-topbar-brand');
  expect(brand, 'the claw mark must be a real button on a phone').not.toBeNull();
  expect(brand!.getAttribute('aria-controls')).toBe('session-sidebar-panel');
  expect(brand!.getAttribute('aria-expanded')).toBe('false');
  expect(brand!.getAttribute('aria-label')).toBe('open the agents drawer');

  brand!.click();
  await settle();
  expect(panel.classList.contains(OPEN), 'the agents drawer did not open').toBe(true);
  expect(panel.querySelector('[role="tablist"]'), 'the drawer opened has no tab row').not.toBeNull();
  expect(brand!.getAttribute('aria-expanded')).toBe('true');
  expect(brand!.getAttribute('aria-label')).toBe('close the agents drawer');

  brand!.click();
  await settle();
  expect(panel.classList.contains(OPEN)).toBe(false);
  expect(brand!.getAttribute('aria-expanded')).toBe('false');
});

test('phone width: aria-expanded follows a drawer closed by its backdrop', async () => {
  phone();
  const { backdrop } = installDrawer();
  const brand = render().querySelector<HTMLButtonElement>('.oc-topbar-brand')!;
  brand.click();
  await settle();
  expect(brand.getAttribute('aria-expanded')).toBe('true');
  backdrop.click();
  await settle();
  expect(brand.getAttribute('aria-expanded')).toBe('false');
});

test('phone width: a drawer already open at mount reads open', async () => {
  phone();
  const { panel } = installDrawer();
  panel.classList.add(OPEN);
  const brand = render().querySelector<HTMLButtonElement>('.oc-topbar-brand')!;
  expect(brand.getAttribute('aria-expanded')).toBe('true');
});

test('NEGATIVE: with no drawer controller loaded, a tap throws nothing', () => {
  phone();
  const brand = render().querySelector<HTMLButtonElement>('.oc-topbar-brand')!;
  expect(() => brand.click()).not.toThrow();
  expect(brand.getAttribute('aria-expanded')).toBe('false');
});

test('desktop width: the mark stays a plain image, not a button', () => {
  installDrawer();
  const toggle = vi.spyOn(g.SessionSidebar as { toggle: () => void }, 'toggle');
  const root = render();
  expect(root.querySelector('.oc-topbar-brand'), 'the mark must not become a button above phone width').toBeNull();
  const mark = root.querySelector<HTMLImageElement>('img.oc-topbar-word');
  expect(mark, 'the plain wordmark image must still be drawn').not.toBeNull();
  expect(mark!.closest('button')).toBeNull();
  expect(mark!.alt).toBe('Carnivore');
  mark!.click();
  expect(toggle).not.toHaveBeenCalled();
});
