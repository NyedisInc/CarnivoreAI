/** @vitest-environment jsdom */
import { afterEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

vi.mock('../../opscenter/api/auth.svelte', () => ({
  authFetch: async () => { throw new Error('offline'); },
}));

import SubagentList from './SubagentList.svelte';
import { setLocale } from '../i18n/index.svelte';
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

test('the list renders its recorded markup', async () => {
  const anchor = document.createElement('button');
  document.body.append(anchor);
  app = mount(SubagentList, { target: document.body, props: { anchor, sessionId: 's', name: 'api work', onClose: () => {} } });
  await new Promise((r) => setTimeout(r, 0));
  flushSync();
  const now = snapshot(document.querySelector('.sal-panel')!);
  expect(now).toBe(reframed(recorded('subagents-list', now), FRAME));
});
