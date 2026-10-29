/** @vitest-environment jsdom */
import { afterEach, expect, test } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import WidgetInfoPopover from './WidgetInfoPopover.svelte';
import { CORE_MANIFESTS } from '../core-manifests';
import { installPopoverPolyfill } from '../../../lib/popover-jsdom-polyfill';
import { setLocale } from '../../../lib/i18n/index.svelte';
import { recorded, reframed, snapshot } from '../../../lib/dialog-frame/goldens';

const FRAME = { addClasses: ['oc-anchored'] };

installPopoverPolyfill();
setLocale('en');

let app: ReturnType<typeof mount> | null = null;
afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.replaceChildren();
});

test('the popover renders its recorded markup', () => {
  const anchor = document.createElement('section');
  document.body.append(anchor);
  app = mount(WidgetInfoPopover, { target: document.body, props: { manifest: CORE_MANIFESTS['core.activity-log']!, anchor } });
  flushSync();
  const now = snapshot(document.querySelector('[data-info-popover]')!);
  expect(now).toBe(reframed(recorded('widget-info-popover', now), FRAME));
});
