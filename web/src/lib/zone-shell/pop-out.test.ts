/** @vitest-environment jsdom */
import { afterEach, expect, test, vi } from 'vitest';

import { popOutFor } from './pop-out';
import { setPanels } from '../cplug-ui/panel-views.svelte';
import { cplugEnablement } from '../../plugins/host/enablement.svelte';
import { CORE_MANIFESTS, manifestById } from '../../opscenter/widgets/core-manifests';
import type { CplugRow } from '../plugins-page/cplugs-adapter';

afterEach(() => {
  setPanels([]);
  cplugEnablement.read = false;
  cplugEnablement.enabled = {};
  vi.restoreAllMocks();
});

test('popOutFor permits authorized popout:true plugin panels with target tail and blocks popout:false panels', () => {
  const openSpy = vi.spyOn(window, 'open').mockReturnValue(null);
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

  const openManifest = manifestById('my-plug.open')!;
  const closedManifest = manifestById('my-plug.closed')!;
  expect(openManifest).toBeDefined();
  expect(closedManifest).toBeDefined();

  const ok = popOutFor(openManifest, openManifest, null, null, undefined, false, 'panel-12345678');
  expect(ok).not.toBeNull();
  ok?.();
  expect(openSpy).toHaveBeenCalledTimes(1);
  expect(String(openSpy.mock.calls[0]?.[0])).toContain('/static/popout.html?widget=my-plug.open%3Apanel-12345678');

  expect(popOutFor(closedManifest, closedManifest, null, null, undefined, false, 'panel-12345678')).toBeNull();

  setPanels([]);
  expect(popOutFor(openManifest, openManifest, null, null, undefined, false, 'panel-12345678')).toBeNull();
  expect(popOutFor({ id: 'unknown.widget', fits: openManifest.fits }, { instancing: 'per-target' }, null, null, undefined, false, 'panel-12345678')).toBeNull();

  cplugEnablement.enabled = { huddle: true };
  cplugEnablement.read = true;
  expect(popOutFor({ id: 'huddle.chat', fits: openManifest.fits }, { instancing: 'per-target' }, null, null, undefined, false, 'agent:7')).not.toBeNull();
  cplugEnablement.enabled = { huddle: false };
  expect(popOutFor({ id: 'huddle.chat', fits: openManifest.fits }, { instancing: 'per-target' }, null, null, undefined, false, 'agent:7')).toBeNull();
});

test('popOutFor keeps core singletons enabled and core family copies blocked', () => {
  const tasks = CORE_MANIFESTS['core.tasks']!;
  expect(popOutFor(tasks, tasks, null, null, undefined)).not.toBeNull();
  expect(popOutFor({ id: 'core.analytics', fits: tasks.fits }, { instancing: 'per-target' }, null, null, undefined)).toBeNull();
});
