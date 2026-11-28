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
      if (path === '/cplugs/tier0-plug/ui/widget') {
        return {
          surface: 'widget',
          stale: false,
          document: { schema: 2, root: { type: 'text', value: 'Tier 0 Widget Content' } },
        };
      }
      if (path === '/cplugs/linear-sync/ui/tab') {
        return {
          surface: 'tab',
          stale: false,
          document: { schema: 2, root: { type: 'text', value: 'Linear Tab Content' } },
        };
      }
      if (path.includes('/view/') || path.includes('/ticket')) {
        return { url: '/api/v1/cplugs/sidecar-plug/view/panel/tok1/index.html', ticket: 'tok1' };
      }
      return {};
    },
  };
});
vi.mock('../plugins/host/enablement.svelte', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../plugins/host/enablement.svelte')>()),
  followEnablement: () => {},
}));

import SingleWidget from './SingleWidget.svelte';
import TabPopout from './TabPopout.svelte';
import PlacementBody from '../lib/zone-shell/PlacementBody.svelte';
import { cplugEnablement } from '../plugins/host/enablement.svelte';
import { isWidgetId, widgetFromSearch } from './popout';
import { setPanels } from '../lib/cplug-ui/panel-views.svelte';
import { setPluginTabs } from '../lib/cplug-ui/plugin-tabs.svelte';
import { manifestById } from '../opscenter/widgets/core-manifests';
import type { CplugRow } from '../lib/plugins-page/cplugs-adapter';

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
  expect(isWidgetId('core.notes:t')).toBe(false);
  expect(isWidgetId('huddle.chat:../x')).toBe(false);
  expect(isWidgetId('Huddle.chat:agent:7')).toBe(false);
});

test('a plugin widget mounts while its plugin is on, with no open-terminal button', async () => {
  cplugEnablement.enabled = { taskmanager: true };
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
  cplugEnablement.enabled = { taskmanager: false };
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

test('authorized popout:true sidecar panel and Tier 0 widget mount in SingleWidget with single header; popout:false stays blocked', async () => {
  const rows: CplugRow[] = [
    {
      id: 'tier0-plug',
      install_key: '12345678',
      runtime: 'sidecar',
      kind: 'declarative',
      enabled: true,
      state: 'active',
      name: 'Tier0 Plug',
      version: '1.0.0',
      trust_tier: 'verified',
      declarative_widget: {
        id: 'board',
        title: 'Tier0 Board',
        mode: 'declarative',
        sizes: ['medium'],
        popout: true,
      },
    },
    {
      id: 'sidecar-plug',
      install_key: 'abcdef12',
      runtime: 'sidecar',
      kind: 'sidecar',
      enabled: true,
      state: 'active',
      name: 'Sidecar Plug',
      version: '1.0.0',
      trust_tier: 'verified',
      views: [
        { name: 'panel', surfaces: ['panel'], popout: true },
        { name: 'locked', surfaces: ['panel'], popout: false },
      ],
    },
  ];
  setPanels(rows);
  cplugEnablement.read = true;

  app = mount(SingleWidget, { target, props: { widget: 'tier0-plug.board:panel-12345678' } });
  flushSync();
  expect(target.querySelector('[data-widget-unavailable]')).toBeNull();
  await vi.waitFor(() => expect(target.textContent).toContain('Tier 0 Widget Content'));
  expect(target.querySelector('.cu-head')).toBeNull();
  unmount(app, { outro: false });

  app = mount(SingleWidget, { target, props: { widget: 'sidecar-plug.panel:panel-abcdef12' } });
  flushSync();
  expect(target.querySelector('[data-widget-unavailable]')).toBeNull();
  expect(target.querySelector('[data-widget-head]')).not.toBeNull();
  unmount(app, { outro: false });

  app = mount(SingleWidget, { target, props: { widget: 'sidecar-plug.locked:panel-abcdef12' } });
  flushSync();
  expect(target.querySelector('[data-widget-unavailable]')).not.toBeNull();
  unmount(app, { outro: false });

  const boardManifest = manifestById('tier0-plug.board')!;
  app = mount(PlacementBody, { target, props: { host: 'popout', manifest: boardManifest, target: 'panel-12345678' } });
  flushSync();
  await vi.waitFor(() => expect(target.textContent).toContain('Tier 0 Widget Content'));
  unmount(app, { outro: false });

  app = mount(PlacementBody, { target, props: { host: 'popout', manifest: boardManifest, target: 'panel-wrong' } });
  flushSync();
  expect(target.querySelector('[data-popout-widget="tier0-plug.board"]')).not.toBeNull();
  expect(target.querySelector('[data-widget-note="none"]')).not.toBeNull();

  setPanels([]);
});

test('TabPopout mounts runtime popout:true sidebar_tab (declarative and view) with WidgetHead mark and NO double .cu-frame__bar header', async () => {
  const rows: CplugRow[] = [
    {
      id: 'linear-sync',
      install_key: 'lin12345',
      runtime: 'sidecar',
      kind: 'declarative',
      enabled: true,
      state: 'active',
      name: 'Linear Sync',
      version: '1.0.0',
      trust_tier: 'verified',
      sidebar_tab: {
        id: 'linear',
        title: 'Linear',
        icon: 'ticket',
        mode: 'declarative',
        popout: true,
      },
    },
    {
      id: 'view-tab-plug',
      install_key: 'vt123456',
      runtime: 'sidecar',
      kind: 'sidecar',
      enabled: true,
      state: 'active',
      name: 'View Tab Plug',
      version: '1.0.0',
      trust_tier: 'unverified_github',
      unverified: true,
      views: [{ name: 'panel', surfaces: ['panel'] }],
      sidebar_tab: {
        id: 'vt',
        title: 'View Tab',
        view: 'panel',
        popout: true,
      },
    },
  ];
  setPluginTabs(rows);

  app = mount(TabPopout, { target, props: { tab: 'cplug-linear-sync-linear' } });
  flushSync();
  expect(target.querySelector('[data-popout-tab="cplug-linear-sync-linear"]')).not.toBeNull();
  expect(target.querySelector('[data-tab-unavailable]')).toBeNull();
  expect(target.querySelector('[data-widget-head]')).not.toBeNull();
  expect(target.querySelector('[data-widget-head] [data-cplug-mark]')).not.toBeNull();
  expect(target.querySelector('.cu-frame__bar')).toBeNull();
  await vi.waitFor(() => expect(target.textContent).toContain('Linear Tab Content'));
  expect(target.querySelector('.cu-frame__bar')).toBeNull();
  unmount(app, { outro: false });

  app = mount(TabPopout, { target, props: { tab: 'cplug-view-tab-plug-vt' } });
  flushSync();
  expect(target.querySelector('[data-popout-tab="cplug-view-tab-plug-vt"]')).not.toBeNull();
  expect(target.querySelector('[data-widget-head]')).not.toBeNull();
  expect(target.querySelector('[data-widget-head] [data-cplug-mark][data-unverified]')).not.toBeNull();
  expect(target.querySelector('.cu-frame__bar')).toBeNull();

  setPluginTabs([]);
});

test('TabPopout waits for unknown compiled enablement and fails closed for disabled or dev-hidden compiled tabs', () => {
  cplugEnablement.read = false;
  cplugEnablement.enabled = {};
  for (const id of ['reviewboard', 'flow', 'devwidgetlab']) {
    app = mount(TabPopout, { target, props: { tab: id } });
    flushSync();
    expect(target.querySelector('[data-tab-loading]')).not.toBeNull();
    expect(target.querySelector('[data-tab-unavailable]')).toBeNull();
    expect(target.querySelector(`[data-popout-tab="${id}"]`)).toBeNull();
    unmount(app, { outro: false });
    app = null;
  }

  cplugEnablement.enabled = { reviewboard: false, taskmanager: false, flow: false };
  cplugEnablement.read = true;
  for (const id of ['reviewboard', 'huddle', 'flow', 'devwidgetlab']) {
    app = mount(TabPopout, { target, props: { tab: id } });
    flushSync();
    expect(target.querySelector('[data-tab-unavailable]')).not.toBeNull();
    expect(target.querySelector('[data-tab-loading]')).toBeNull();
    expect(target.querySelector(`[data-popout-tab="${id}"]`)).toBeNull();
    unmount(app, { outro: false });
    app = null;
  }

  cplugEnablement.enabled = { taskmanager: true };
  cplugEnablement.read = true;
  app = mount(TabPopout, { target, props: { tab: 'huddle' } });
  flushSync();
  expect(target.querySelector('[data-popout-tab="huddle"]')).not.toBeNull();
  expect(target.querySelector('[data-tab-unavailable]')).toBeNull();
});
