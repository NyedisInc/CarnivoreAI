/** @vitest-environment jsdom */
import { afterEach, expect, test } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';
import SettingsOverlay from './SettingsOverlay.svelte';
import { openConfigure } from './configure.svelte';
import { createItemSettingsController } from '../../../lib/item-settings/item-settings-controller.svelte';
import { memoryFetcher } from '../../../lib/item-settings/memory-fetcher';
import type { Fetcher } from '../../../lib/item-settings/api';
import { CORE_MANIFESTS } from '../core-manifests';
import { installPopoverPolyfill } from '../../../lib/popover-jsdom-polyfill';
import { t } from '../../../lib/i18n/index.svelte';
import { recorded, reframed, snapshot } from '../../../lib/dialog-frame/goldens';

/** The move's only intended change: the frame is `AnchoredPopup`'s, which adds its own class. */
const FRAME = { addClasses: ['oc-anchored'] };

installPopoverPolyfill();

const ID = 'core.activity-log';
let app: ReturnType<typeof mount> | null = null;
afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
});

test('the overlay renders its recorded markup', async () => {
  const controller = createItemSettingsController('widget', ID, t, memoryFetcher({ [ID]: CORE_MANIFESTS[ID]!.settings! }) as Fetcher, async () => {});
  const anchor = document.createElement('section');
  document.body.append(anchor);
  openConfigure('activity-log');
  app = mount(SettingsOverlay, { target: document.body, props: { widgetId: ID, title: 'activity log', anchor, hasSchema: true, controller } });
  for (let i = 0; i < 4; i += 1) await Promise.resolve();
  await tick();
  flushSync();
  const now = snapshot(document.querySelector(`[data-settings-overlay="${ID}"]`)!);
  expect(now).toBe(reframed(recorded('settings-overlay', now), FRAME));
});
