/** @vitest-environment jsdom */
import { afterEach, expect, test } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import ColorSwatches from './ColorSwatches.svelte';
import { installPopoverPolyfill } from '../popover-jsdom-polyfill';
import { createI18n } from '../../../../client/js/i18n/runtime.js';
import { recorded, reframed, snapshot } from '../dialog-frame/goldens';

const FRAME = { addClasses: ['oc-anchored'] };

const i18n = createI18n();
const t = (key: string, params?: Record<string, unknown> | null) => i18n.t(key, params);
installPopoverPolyfill();

let app: ReturnType<typeof mount> | null = null;
afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.replaceChildren();
});

test('the popup renders its recorded markup', () => {
  app = mount(ColorSwatches, { target: document.body, props: { value: '#00af87', t, disabled: false, onPick: () => {} } });
  flushSync();
  document.querySelector<HTMLButtonElement>('[data-ledger="color-chip"]')!.click();
  flushSync();
  const now = snapshot(document.querySelector('.ledger-tpick__panel')!);
  expect(now).toBe(reframed(recorded('color-swatches', now), FRAME));
});
