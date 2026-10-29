/** @vitest-environment jsdom */
import { afterEach, expect, test } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import ProjectColorPopover from './ProjectColorPopover.svelte';
import { setLocale, t } from '../i18n/index.svelte';
import { recorded, reframed, snapshot } from '../dialog-frame/goldens';

/** The move's only intended change: the frame is `AnchoredPopup`'s, which adds its own class. */
const FRAME = { addClasses: ['oc-anchored'] };

setLocale('en');

let app: ReturnType<typeof mount> | null = null;
afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.replaceChildren();
});

test('the popover renders its recorded markup', () => {
  const anchor = document.createElement('button');
  document.body.append(anchor);
  app = mount(ProjectColorPopover, { target: document.body, props: { initial: '#336699', t, anchor, onOk: () => {}, onCancel: () => {} } });
  flushSync();
  const now = snapshot(document.querySelector('[data-project-color-popover]')!);
  expect(now).toBe(reframed(recorded('project-color-popover', now), FRAME));
});
