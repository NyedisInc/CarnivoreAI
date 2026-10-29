/** @vitest-environment jsdom */
import { afterEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

vi.mock('../../opscenter/api/auth.svelte', async (original) => ({
  ...(await original<Record<string, unknown>>()),
  authFetch: async (path: string) => {
    if (path.endsWith('/send/check')) return { move: { ok: true }, copy: { ok: true }, fresh: { ok: true }, project_on_target: true, project_addable: { ok: true } };
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
import type { PackMachine } from '../pack-machines/pack-machines-store.svelte';
import SendToModal from './SendToModal.svelte';

setLocale('en');

const machine = { install_id: 'hosta', label: 'hosta', is_self: false, is_master: false, paired: true, state: 'connected', capabilities: [],
  specs: null, age_seconds: 1, snapshot: null } as unknown as PackMachine;

const mounted: ReturnType<typeof mount>[] = [];
afterEach(async () => {
  for (const c of mounted.splice(0)) await unmount(c);
  document.body.replaceChildren();
});

test('the dialog renders its recorded markup', async () => {
  auth.state = 'signed-in';
  const root = document.createElement('div');
  document.body.append(root);
  mounted.push(mount(SendToModal, { target: root, props: { uuid: 'u1', name: 'api', machine, projectName: 'ledgerbot', onClose: vi.fn() } }));
  await new Promise((r) => setTimeout(r, 0));
  flushSync();
  const now = snapshot(root.querySelector('[data-send-to-modal]')!);
  expect(recordedParts(recording('send-to')).children).toHaveLength(3);
  expect(now).toBe(onShell('send-to'));
});
