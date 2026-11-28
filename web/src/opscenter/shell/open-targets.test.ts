/** @vitest-environment jsdom */
import { afterEach, expect, test, vi } from 'vitest';

vi.mock('../../opscenter/api', () => ({
  isDemo: () => false,
  sessions: { status: 'idle', data: null },
  transport: { state: 'unknown' },
}));

import { menuRowPopout, openTargets } from './open-targets';
import { setPluginTabs } from '../../lib/cplug-ui/plugin-tabs.svelte';
import { setPanels } from '../../lib/cplug-ui/panel-views.svelte';
import { pluginsStore, type StoreCplugRow } from '../../lib/plugins/store.svelte';
import { cplugEnablement } from '../../plugins/host/enablement.svelte';
import type { CplugRow } from '../../lib/plugins-page/cplugs-adapter';

afterEach(() => {
  setPluginTabs([]);
  setPanels([]);
  pluginsStore.resetForTest();
  cplugEnablement.read = false;
  cplugEnablement.enabled = {};
  vi.restoreAllMocks();
});

test('openTargets includes runtime popout:true tabs and active consented popout slot entries', () => {
  const openSpy = vi.spyOn(window, 'open').mockReturnValue(null);
  const rows: StoreCplugRow[] = [
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
      granted_ui_slots: ['popout'],
      routes: ['open_board'],
      sidebar_tab: {
        id: 'linear',
        title: 'Linear Tab',
        popout: true,
      },
      declarative_widget: {
        id: 'issues',
        title: 'Linear Issues',
        mode: 'declarative',
        popout: true,
      },
      ui_slots: ['popout'],
      ui_contribute: {
        popout: [
          { id: 'linear-widget', label: 'Linear Issues', widget: 'linear-sync.issues:panel-lin12345' },
          { id: 'linear-action', label: 'Open Board', route: 'open_board' },
        ],
      },
    },
    {
      id: 'private-plug',
      install_key: 'prv12345',
      runtime: 'sidecar',
      kind: 'declarative',
      enabled: true,
      state: 'active',
      name: 'Private Plug',
      version: '1.0.0',
      trust_tier: 'verified',
      sidebar_tab: {
        id: 'hidden',
        title: 'Hidden Tab',
        popout: false,
      },
      views: [{ name: 'locked', surfaces: ['panel'], popout: false }],
    },
  ];
  pluginsStore.rows = rows;
  pluginsStore.read = true;
  pluginsStore.slotsRead = true;
  pluginsStore.slots = {
    popout: [
      {
        plugin_id: 'linear-sync',
        install_key: 'lin12345',
        slot: 'popout',
        declared_slot: 'popout',
        item: { id: 'linear-widget', label: 'Linear Issues', widget: 'linear-sync.issues:panel-lin12345' },
      },
      {
        plugin_id: 'linear-sync',
        install_key: 'lin12345',
        slot: 'popout',
        declared_slot: 'popout',
        item: { id: 'pwn-disabled', label: 'Disabled Secret', widget: 'disabled-plug.secret:panel-dis12345' },
      },
      {
        plugin_id: 'linear-sync',
        install_key: 'lin12345',
        slot: 'popout',
        declared_slot: 'popout',
        item: { id: 'pwn-locked', label: 'Locked Panel', widget: 'private-plug.locked:panel-prv12345' },
      },
      {
        plugin_id: 'linear-sync',
        install_key: 'lin12345',
        slot: 'popout',
        declared_slot: 'popout',
        item: { id: 'pwn-core', label: 'Core Terminal', widget: 'core.terminal' },
      },
      {
        plugin_id: 'linear-sync',
        install_key: 'lin12345',
        slot: 'popout',
        declared_slot: 'popout',
        item: { id: 'pwn-huddle', label: 'Disabled Huddle', widget: 'huddle.chat:agent:7' },
      },
    ],
  };
  cplugEnablement.enabled = { huddle: false };
  cplugEnablement.read = true;

  setPanels(rows as unknown as readonly CplugRow[]);
  setPluginTabs(rows as unknown as readonly CplugRow[]);

  const targets = openTargets();
  expect(targets.some((t) => t.id === 'tab:cplug-linear-sync-linear')).toBe(true);
  expect(targets.some((t) => t.id === 'tab:cplug-private-plug-hidden')).toBe(false);
  expect(targets.some((t) => t.id === 'plugin:linear-sync:linear-widget')).toBe(true);
  expect(targets.some((t) => t.id === 'plugin:linear-sync:pwn-disabled')).toBe(false);
  expect(targets.some((t) => t.id === 'plugin:linear-sync:pwn-locked')).toBe(false);
  expect(targets.some((t) => t.id === 'plugin:linear-sync:pwn-core')).toBe(false);
  expect(targets.some((t) => t.id === 'plugin:linear-sync:pwn-huddle')).toBe(false);

  const rowAction = menuRowPopout('cplug-linear-sync-linear');
  expect(rowAction).not.toBeNull();
  rowAction?.();
  expect(openSpy).toHaveBeenCalled();
  expect(String(openSpy.mock.calls[0]?.[0])).toContain('/static/popout.html?tab=cplug-linear-sync-linear');
});

test('openTargets gates popout slot tab entries on compiled plugin enablement and developer mode', () => {
  const rows: StoreCplugRow[] = [
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
      granted_ui_slots: ['popout'],
      sidebar_tab: { id: 'linear', title: 'Linear Tab', popout: true },
      ui_slots: ['popout'],
    },
    {
      id: 'private-plug',
      install_key: 'prv12345',
      runtime: 'sidecar',
      kind: 'declarative',
      enabled: true,
      state: 'active',
      name: 'Private Plug',
      version: '1.0.0',
      trust_tier: 'verified',
      sidebar_tab: { id: 'hidden', title: 'Hidden Tab', popout: false },
    },
  ];
  pluginsStore.rows = rows;
  pluginsStore.read = true;
  pluginsStore.slotsRead = true;
  pluginsStore.slots = {
    popout: [
      { plugin_id: 'linear-sync', install_key: 'lin12345', slot: 'popout', declared_slot: 'popout', item: { id: 'pwn-rb', label: 'Disabled Reviewboard', tab: 'reviewboard' } },
      { plugin_id: 'linear-sync', install_key: 'lin12345', slot: 'popout', declared_slot: 'popout', item: { id: 'pwn-huddle', label: 'Disabled Huddle', tab: 'huddle' } },
      { plugin_id: 'linear-sync', install_key: 'lin12345', slot: 'popout', declared_slot: 'popout', item: { id: 'pwn-flow', label: 'Disabled Flow', tab: 'flow' } },
      { plugin_id: 'linear-sync', install_key: 'lin12345', slot: 'popout', declared_slot: 'popout', item: { id: 'pwn-devlab', label: 'Hidden DevWidgetLab', tab: 'devwidgetlab' } },
      { plugin_id: 'linear-sync', install_key: 'lin12345', slot: 'popout', declared_slot: 'popout', item: { id: 'pwn-private-tab', label: 'Private Tab', tab: 'cplug-private-plug-hidden' } },
      { plugin_id: 'linear-sync', install_key: 'lin12345', slot: 'popout', declared_slot: 'popout', item: { id: 'ok-runtime-tab', label: 'Linear Runtime Tab', tab: 'cplug-linear-sync-linear' } },
    ],
  };
  setPluginTabs(rows as unknown as readonly CplugRow[]);

  cplugEnablement.enabled = { reviewboard: false, huddle: false, flow: false };
  cplugEnablement.read = true;

  let targets = openTargets();
  expect(targets.some((t) => t.id === 'plugin:linear-sync:pwn-rb')).toBe(false);
  expect(targets.some((t) => t.id === 'plugin:linear-sync:pwn-huddle')).toBe(false);
  expect(targets.some((t) => t.id === 'plugin:linear-sync:pwn-flow')).toBe(false);
  expect(targets.some((t) => t.id === 'plugin:linear-sync:pwn-devlab')).toBe(false);
  expect(targets.some((t) => t.id === 'plugin:linear-sync:pwn-private-tab')).toBe(false);
  expect(targets.some((t) => t.id === 'plugin:linear-sync:ok-runtime-tab')).toBe(true);

  cplugEnablement.enabled = { reviewboard: true, huddle: true, flow: true, devwidgetlab: true };
  targets = openTargets();
  expect(targets.some((t) => t.id === 'plugin:linear-sync:pwn-rb')).toBe(true);
  expect(targets.some((t) => t.id === 'plugin:linear-sync:pwn-huddle')).toBe(true);
  expect(targets.some((t) => t.id === 'plugin:linear-sync:pwn-flow')).toBe(true);
  expect(targets.some((t) => t.id === 'plugin:linear-sync:pwn-devlab')).toBe(true);
});
