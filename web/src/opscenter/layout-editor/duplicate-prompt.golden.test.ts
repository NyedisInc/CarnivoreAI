/** @vitest-environment jsdom */
import { afterEach, expect, test } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import DuplicatePrompt from './DuplicatePrompt.svelte';
import { askDuplicate, closeDuplicate } from './duplicate-prompt.svelte';
import { installPopoverPolyfill } from '../../lib/popover-jsdom-polyfill';
import { setLocale } from '../../lib/i18n/index.svelte';
import { recorded, reframed, snapshot } from '../../lib/dialog-frame/goldens';

const FRAME = { addClasses: ['oc-anchored'] };

installPopoverPolyfill();
setLocale('en');

let app: ReturnType<typeof mount> | null = null;
afterEach(() => {
  if (app) unmount(app);
  app = null;
  closeDuplicate();
  document.body.replaceChildren();
});

test('the prompt renders its recorded markup', () => {
  app = mount(DuplicatePrompt, { target: document.body });
  askDuplicate({ kind: 'copy', title: 'providers', x: 10, y: 10, onCopy: () => {}, onMove: () => {} });
  flushSync();
  const now = snapshot(document.querySelector('[data-duplicate-prompt]')!);
  expect(now).toBe(reframed(recorded('duplicate-prompt', now), FRAME));
});
