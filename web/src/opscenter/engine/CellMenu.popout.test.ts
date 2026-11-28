/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

vi.mock('../api', () => ({
  isDemo: () => false,
  sessions: { status: 'idle', data: null },
  transport: { state: 'unknown' },
}));

import CellMenu from './CellMenu.svelte';
import { homeLayout } from './layout.svelte';
import { setPanels } from '../../lib/cplug-ui/panel-views.svelte';
import type { CplugRow } from '../../lib/plugins-page/cplugs-adapter';
import type { SlotId } from './types';

const popoverProto = HTMLElement.prototype as unknown as Record<string, unknown>;
popoverProto.showPopover ??= function () {};
popoverProto.hidePopover ??= function () {};

let app: ReturnType<typeof mount> | null = null;
let target: HTMLElement;

beforeEach(() => {
  target = document.createElement('div');
  document.body.append(target);
  const rows: CplugRow[] = [
    {
      id: 'my-plug',
      install_key: '12345678',
      runtime: 'sidecar',
      kind: 'sidecar',
      enabled: true,
      state: 'active',
      name: 'My Plug',
      version: '1.0.0',
      trust_tier: 'verified',
      views: [
        { name: 'open', surfaces: ['panel'], popout: true },
        { name: 'closed', surfaces: ['panel'], popout: false },
      ],
    },
  ];
  setPanels(rows);
});

afterEach(() => {
  if (app) unmount(app, { outro: false });
  app = null;
  setPanels([]);
  document.body.innerHTML = '';
  vi.restoreAllMocks();
});

test('CellMenu offers pop-out for popout:true plugin slot and omits it for popout:false slot', () => {
  const anchor = document.createElement('button');
  document.body.append(anchor);

  app = mount(CellMenu, {
    target,
    props: {
      id: 'my-plug.open:panel-12345678' as SlotId,
      anchor,
      onClose: () => {},
      store: homeLayout,
    },
  });
  flushSync();
  const openBtn = document.querySelector('[data-node="pop-out"]');
  expect(openBtn).not.toBeNull();
  const winOpen = vi.spyOn(window, 'open').mockReturnValue(null);
  (openBtn as HTMLElement).click();
  expect(winOpen).toHaveBeenCalledTimes(1);
  expect(String(winOpen.mock.calls[0]?.[0])).toContain('/static/popout.html?widget=my-plug.open%3Apanel-12345678');

  unmount(app, { outro: false });
  app = mount(CellMenu, {
    target,
    props: {
      id: 'my-plug.closed:panel-12345678' as SlotId,
      anchor,
      onClose: () => {},
      store: homeLayout,
    },
  });
  flushSync();
  expect(document.querySelector('[data-node="pop-out"]')).toBeNull();

  unmount(app, { outro: false });
  setPanels([]);
  app = mount(CellMenu, {
    target,
    props: {
      id: 'my-plug.open:panel-12345678' as SlotId,
      anchor,
      onClose: () => {},
      store: homeLayout,
    },
  });
  flushSync();
  expect(document.querySelector('[data-node="pop-out"]')).toBeNull();
});
