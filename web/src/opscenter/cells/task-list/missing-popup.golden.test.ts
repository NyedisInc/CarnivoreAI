/** @vitest-environment jsdom */
import { afterEach, expect, test } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import MissingPopup from './MissingPopup.svelte';
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

test('the card renders its recorded markup', () => {
  app = mount(MissingPopup, { target: document.body, props: { onClose: () => {} } });
  flushSync();
  const now = snapshot(document.querySelector('[data-task-manager-list-warn]')!);
  expect(now).toBe(reframed(recorded('missing-popup', now), FRAME));
});
