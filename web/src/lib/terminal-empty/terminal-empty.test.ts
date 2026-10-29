/** @vitest-environment jsdom */
import { afterEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

vi.mock('../../opscenter/api', async () => ({
  ...(await import('../../opscenter/api/host')),
}));

import TerminalEmpty from './TerminalEmpty.svelte';
import { openSession, openSessions } from '../../opscenter/api/host';
import { setLocale } from '../i18n/index.svelte';

setLocale('en');

type Globals = {
  TerminalEmptyEntry?: unknown;
  CloudeWeb?: unknown;
  SessionSidebar?: unknown;
};
const g = globalThis as Globals;

const mounted: ReturnType<typeof mount>[] = [];
afterEach(async () => {
  for (const c of mounted.splice(0)) await unmount(c);
  document.body.replaceChildren();
  delete g.TerminalEmptyEntry;
  delete g.CloudeWeb;
  delete g.SessionSidebar;
  vi.restoreAllMocks();
});

function render(component: never, props: Record<string, unknown> = {}): HTMLElement {
  const target = document.createElement('div');
  document.body.append(target);
  mounted.push(mount(component, { target, props }));
  flushSync();
  return target;
}


test('openSessions opens the sessions view, never the empty terminal page', () => {
  const show = vi.fn(() => true);
  const openSessionsScreen = vi.fn(() => true);
  g.TerminalEmptyEntry = { show };
  g.CloudeWeb = { openSessionsScreen };
  expect(openSessions()).toBe(true);
  expect(openSessionsScreen).toHaveBeenCalledTimes(1);
  expect(show).not.toHaveBeenCalled();
});

test('NEGATIVE: with the sessions view missing, openSessions says so and does nothing', () => {
  const err = vi.spyOn(console, 'error').mockImplementation(() => {});
  expect(openSessions()).toBe(false);
  expect(err).toHaveBeenCalledWith(expect.stringContaining('CloudeWeb.openSessionsScreen'));
});

test('NEGATIVE CONTROL: a session click still attaches and never shows the empty page', () => {
  const show = vi.fn(() => true);
  const attach = vi.fn(async () => {});
  g.TerminalEmptyEntry = { show };
  g.CloudeWeb = { launchpad: { openRunningSession: attach } };
  expect(openSession('adopted:cloude_api', 'cloude_api')).toBe(true);
  expect(attach).toHaveBeenCalledWith('adopted:cloude_api', 'cloude_api');
  expect(show).not.toHaveBeenCalled();
});

test('the panel paints the Carnivore Default background and the catalog copy', () => {
  const root = render(TerminalEmpty as never);
  const img = root.querySelector<HTMLImageElement>('.terminal-empty__art');
  expect(img?.getAttribute('src')).toBe('/static/css/themes/carnivore/background.webp');
  expect(root.querySelector('.terminal-empty__title')?.textContent).toBe('no session selected');
  expect(root.querySelector('.terminal-empty__body')?.textContent).toContain('agents drawer');
});

test('its buttons open the drawer and the existing new session flow', () => {
  const open = vi.fn();
  const create = vi.fn(async () => {});
  g.SessionSidebar = { open };
  g.CloudeWeb = { launchpad: { createNewSession: create } };
  const root = render(TerminalEmpty as never);
  root.querySelector<HTMLButtonElement>('[data-terminal-empty="drawer"]')!.click();
  root.querySelector<HTMLButtonElement>('[data-terminal-empty="new"]')!.click();
  expect(open).toHaveBeenCalledTimes(1);
  expect(create).toHaveBeenCalledTimes(1);
});
