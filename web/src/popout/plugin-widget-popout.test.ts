/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

vi.mock('../opscenter/api', () => ({
  isDemo: () => false,
  auth: { state: 'signed-in' },
  initAuth: () => {},
  startEvents: () => {},
  sessions: { status: 'idle', data: null },
  transport: { state: 'unknown' },
}));
vi.mock('../opscenter/api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../opscenter/api/auth.svelte')>();
  return {
    ...real,
    authFetch: async (path: string) => {
      if (path === '/swarm/agents/7') return { id: 7, display_name: 'Loki', rank: 'project', state: 'asleep', thread_key: '12', session_id: 'ses_9', tmux_session: null };
      if (path.startsWith('/swarm/agents/7/conversation')) return { entries: [], cursor: null };
      return {};
    },
  };
});
vi.mock('../cplugs/host/enablement.svelte', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../cplugs/host/enablement.svelte')>()),
  followEnablement: () => {},
}));

import SingleWidget from './SingleWidget.svelte';
import { cplugEnablement } from '../cplugs/host/enablement.svelte';
import { isWidgetId, widgetFromSearch } from './popout';

// jsdom has no popover API; the one item menu shows its levels through it (#2613).
const popoverProto = HTMLElement.prototype as unknown as Record<string, unknown>;
popoverProto.showPopover ??= function () {};
popoverProto.hidePopover ??= function () {};

const SLOT = 'huddle.chat:agent:7';
let app: ReturnType<typeof mount> | null = null;
let target: HTMLElement;

beforeEach(() => {
  (globalThis as { ResizeObserver?: unknown }).ResizeObserver = class {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
  };
  target = document.createElement('div');
  document.body.append(target);
});

afterEach(() => {
  if (app) unmount(app, { outro: false });
  app = null;
  document.body.innerHTML = '';
  cplugEnablement.read = false;
  cplugEnablement.enabled = {};
});

test('the url accepts a plugin slot id and still refuses a malformed one', () => {
  expect(widgetFromSearch(`?widget=${SLOT}`)).toBe(SLOT);
  expect(isWidgetId('huddle.chat')).toBe(false);
  expect(isWidgetId('huddle.chat:../x')).toBe(false);
  expect(isWidgetId('Huddle.chat:agent:7')).toBe(false);
});

test('a plugin widget mounts while its plugin is on, with no open-terminal button', async () => {
  cplugEnablement.enabled = { huddle: true };
  cplugEnablement.read = true;
  app = mount(SingleWidget, { target, props: { widget: SLOT } });
  flushSync();
  expect(target.querySelector(`[data-popout-widget="${SLOT}"]`)).not.toBeNull();
  expect(target.querySelector('[data-widget-unavailable]')).toBeNull();
  await vi.waitFor(() => expect(target.querySelector('[data-chat-state="ok"]')).not.toBeNull());
  await vi.waitFor(() => expect(target.querySelector('[data-chat-bar]')).not.toBeNull());
  target.querySelector('[data-chat-bar]')!.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, cancelable: true, clientX: 40, clientY: 10 }));
  flushSync();
  expect(document.querySelector('#item-menu-host [data-node]')).not.toBeNull();
  expect(document.querySelector('[data-node="terminal"]')).toBeNull();
});

test('a disabled plugin, and an unknown one, show unavailable; nothing shows before the answer', () => {
  cplugEnablement.enabled = { huddle: false };
  cplugEnablement.read = true;
  app = mount(SingleWidget, { target, props: { widget: SLOT } });
  flushSync();
  expect(target.querySelector('[data-widget-unavailable]')).not.toBeNull();
  expect(target.querySelector('[data-popout-widget]')).toBeNull();
  unmount(app, { outro: false });
  app = mount(SingleWidget, { target, props: { widget: 'nope.chat:agent:7' } });
  flushSync();
  expect(target.querySelector('[data-widget-unavailable]')).not.toBeNull();
  unmount(app, { outro: false });
  cplugEnablement.read = false;
  app = mount(SingleWidget, { target, props: { widget: SLOT } });
  flushSync();
  expect(target.querySelector('[data-widget-unavailable]')).toBeNull();
  expect(target.querySelector('[data-widget-loading]')).not.toBeNull();
});
