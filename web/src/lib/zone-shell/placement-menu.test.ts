/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import { DECLARED_PROBE_ACTION, declaringLog, fakeActive } from '../session-rail/test-support.svelte';

vi.mock('../../opscenter/api', async (importOriginal) => {
  const real = await importOriginal<Record<string, unknown>>();
  return { ...real, sessions: { data: [{ session_row_id: 7, project_id: 4, session: { id: 'ses_1', working_dir: '/w' } }] }, primarySessionId: () => 'ses_1' };
});
vi.mock('../../opscenter/lib/active-terminal', async () => {
  const { fakeActive: active } = await import('../session-rail/test-support.svelte');
  return { activeTerminalSessionId: () => active.id, activeTerminalSlot: () => 'terminal:@primary' };
});
vi.mock('../../opscenter/cells/registry', async (importOriginal) => {
  const { DeclaringProbe } = await import('../session-rail/test-support.svelte');
  return { ...(await importOriginal<Record<string, unknown>>()), entryFor: () => ({ component: DeclaringProbe }) };
});

import PlacementMenuHost from './PlacementMenuHost.svelte';
import GlanceMenu from '../drawer-zone/GlanceMenu.svelte';
import { drawerZone } from '../drawer-zone/zone-store.svelte';
import { CORE_MANIFESTS } from '../../opscenter/widgets/core-manifests';
import { MENU_HOSTS, placementMenu, type MenuHost } from './placement-menu';
import { CORE_ID } from '../widget-menu/model';
import { HOST_LOOKS, type BodyHost } from './host-looks';
import type { DeclaredAction } from '../../opscenter/widgets/menu/declared-actions.svelte';
import type { OptionNodesInput } from '../widget-menu/option-nodes';

const TASKS = CORE_MANIFESTS['core.tasks']!;
const proto = HTMLElement.prototype as unknown as Record<string, unknown>;
proto.showPopover ??= function () {};
proto.hidePopover ??= function () {};

const ids = (): (string | undefined)[] => [...document.querySelectorAll<HTMLElement>('.acm-item')].map((el) => el.dataset['node']);
const apps: object[] = [];

beforeEach(() => {
  fakeActive.id = 'ses_1';
  Object.assign(declaringLog, { live: 0, made: 0, runs: [] });
  vi.stubGlobal('ResizeObserver', class { observe(): void {} unobserve(): void {} disconnect(): void {} });
});
afterEach(() => {
  while (apps.length) unmount(apps.pop()!, { outro: false });
  document.body.replaceChildren();
});

function shared(): { options: OptionNodesInput; declared: DeclaredAction[] } {
  return {
    options: { manifest: TASKS, cell: TASKS, view: null, values: undefined, translate: (k) => k, pickView: () => {}, write: () => {}, openForm: () => {} },
    declared: [{ id: 'refresh', label: 'refresh', run: () => {} }],
  };
}

describe('the pure builder: six hosts, one widget list', () => {
  test('core.tasks offers the same widget groups and the scope switch in normal mode on every host, and only the tab host has the tab group', () => {
    const lists = MENU_HOSTS.map((host: MenuHost) => {
      const tab = host === 'tab' ? { close: () => {}, moveTo: () => {}, splitRight: () => {}, splitDown: () => {} } : undefined;
      return { host, ids: placementMenu({ host, editing: false, onClose: () => {}, ...shared(), popOut: () => {}, tab }).map((node) => node.id) };
    });
    for (const { host, ids: got } of lists) {
      expect(got, host).toEqual(expect.arrayContaining(['refresh', 'session', 'all', CORE_ID.popOut]));
    }
    const tabGroup = [CORE_ID.moveTab, CORE_ID.splitRight, CORE_ID.splitDown, CORE_ID.closeTab];
    for (const { host, ids: got } of lists) {
      if (host === 'tab') expect(got).toEqual(expect.arrayContaining(tabGroup));
      else expect(got.filter((id) => tabGroup.includes(id as never)), host).toEqual([]);
    }
    const widgetOnly = (host: MenuHost): (string | undefined)[] => lists.find((one) => one.host === host)!.ids.filter((id) => !(['move-tab', 'split-right', 'split-down', 'close-tab'] as (string | undefined)[]).includes(id));
    for (const host of MENU_HOSTS) expect(widgetOnly(host), host).toEqual(widgetOnly('bar-key'));
  });

  test('the grid host (wrapper package Z-3) offers the same widget groups but no views: a grid slot names the cell it draws', () => {
    for (const editing of [false, true]) {
      const got = placementMenu({ host: 'grid', editing, onClose: () => {}, ...shared(), popOut: () => {} }).map((node) => node.id);
      expect(got, `editing ${editing}`).toContain('refresh');
      expect(got.filter((id) => id === 'session' || id === 'all'), `editing ${editing}`).toEqual([]);
    }
    expect(placementMenu({ host: 'bar-key', editing: true, onClose: () => {}, ...shared() }).map((node) => node.id)).toContain('all');
  });

  test('a widget that is not a session | all sessions pair gets no scope switch and keeps its looks in edit mode only', () => {
    const notes = CORE_MANIFESTS['core.notes']!;
    const input = { ...shared(), options: { ...shared().options, manifest: notes, cell: notes } };
    expect(placementMenu({ host: 'bar-key', editing: false, onClose: () => {}, ...input }).map((n) => n.id)).not.toContain('all');
  });
});

describe('mounted: a menu whose body is not drawn still carries the widget\'s declared actions', () => {
  test('every host mounts the body unseen, lists the declared action and the scope switch, and the unseen copy goes with the menu', () => {
    for (const host of ['bar-key', 'drawer-card', 'popout', 'tab'] as MenuHost[]) {
      const bodyHost: BodyHost = host === 'bar-key' ? 'rail' : host === 'popout' ? 'popout' : 'drawer';
      const target = document.createElement('div');
      document.body.appendChild(target);
      const anchor = document.createElement('button');
      document.body.appendChild(anchor);
      const picked: string[] = [];
      const app = mount(PlacementMenuHost, {
        target,
        props: { host, bodyHost, manifest: TASKS, placementKey: 'core.tasks', pickView: (v: string) => picked.push(v), anchor, label: 'menu', onClose: () => {} },
      });
      flushSync();
      expect(ids(), host).toEqual(expect.arrayContaining([DECLARED_PROBE_ACTION, 'session', 'all']));
      expect(declaringLog.live, host).toBe(1);
      document.querySelector<HTMLElement>('[data-node="all"]')!.click();
      expect(picked, host).toEqual(['all']);
      unmount(app, { outro: false });
      document.body.replaceChildren();
      expect(declaringLog.live, host).toBe(0);
    }
    expect(HOST_LOOKS.drawer.keyFor(TASKS, null, null)).toContain('core.tasks');
  });

  test('a glance tile: its menu has the declared action and the scope switch, and picking all sessions swaps the tile\'s widget', () => {
    const swapped: [string, string][] = [];
    const spy = vi.spyOn(drawerZone, 'setGlanceWidget').mockImplementation((id, widget) => void swapped.push([id, widget]));
    const target = document.createElement('div');
    document.body.appendChild(target);
    const anchor = document.createElement('button');
    document.body.appendChild(anchor);
    apps.push(mount(GlanceMenu, { target, props: { placement: 'g-1', widget: 'core.tasks', options: {}, anchor, onClose: () => {}, onSettings: () => {} } }));
    flushSync();
    expect(ids()).toEqual(expect.arrayContaining([DECLARED_PROBE_ACTION, 'session', 'all', CORE_ID.popOut, CORE_ID.closeWidget]));
    document.querySelector<HTMLElement>('[data-node="all"]')!.click();
    expect(swapped).toEqual([['g-1', 'core.tasks-all']]);
    spy.mockRestore();
  });

  test('a glance tile already drawing the all sessions widget shows the all sessions side of the switch checked', () => {
    const target = document.createElement('div');
    document.body.appendChild(target);
    const anchor = document.createElement('button');
    document.body.appendChild(anchor);
    apps.push(mount(GlanceMenu, { target, props: { placement: 'g-2', widget: 'core.tasks-all', options: {}, anchor, onClose: () => {}, onSettings: () => {} } }));
    flushSync();
    expect(document.querySelector('[data-node="all"]')?.getAttribute('aria-checked')).toBe('true');
    expect(document.querySelector('[data-node="session"]')?.getAttribute('aria-checked')).toBe('false');
  });
});
