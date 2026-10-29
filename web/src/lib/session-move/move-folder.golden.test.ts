/** @vitest-environment jsdom */
import { afterEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

vi.mock('../../opscenter/api/auth.svelte', async (original) => ({
  ...(await original<Record<string, unknown>>()),
  authFetch: async (path: string) => {
    if (path === '/projects') return [{ id: 3, name: 'app', path: '/p/app' }];
    throw new Error(`unexpected ${path}`);
  },
}));

import { auth } from '../../opscenter/api/auth.svelte';
import { setLocale } from '../i18n/index.svelte';
import { recorded, snapshot } from '../dialog-frame/goldens';

import MoveFolderModal from './MoveFolderModal.svelte';

setLocale('en');

const mounted: ReturnType<typeof mount>[] = [];
afterEach(async () => {
  for (const c of mounted.splice(0)) await unmount(c);
  document.body.replaceChildren();
});

test('the dialog renders its recorded markup', async () => {
  auth.state = 'signed-in';
  const root = document.createElement('div');
  document.body.append(root);
  mounted.push(mount(MoveFolderModal, { target: root, props: { uuid: 'u1', name: 'api', onClose: vi.fn() } }));
  await new Promise((r) => setTimeout(r, 0));
  flushSync();
  const now = snapshot(root.querySelector('[data-move-modal]')!);
  expect(now).toBe(recorded('move-folder', now));
});
