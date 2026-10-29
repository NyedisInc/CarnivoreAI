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
import { indent, recordedParts, recording, reframed, snapshot } from '../dialog-frame/goldens';

const FRAME = { addClasses: ['modal-overlay', 'stm-modal'], removeClasses: ['popup-focus', 'stm'], attrs: { 'aria-modal': 'true' } };

function onShell(name: string): string {
  const { frame, children: [title = '', body = '', foot = ''] } = recordedParts(recording(name));
  return `${reframed(frame, FRAME)}  <div class="modal-content popup-focus stm" data-oc-base="">\n${indent(title, 2)}`
    + `    <div class="modal-body">\n${indent(body, 3)}    <div class="modal-footer">\n${indent(foot, 3)}`;
}
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
  expect(recordedParts(recording('move-folder')).children).toHaveLength(3);
  expect(now).toBe(onShell('move-folder'));
});
