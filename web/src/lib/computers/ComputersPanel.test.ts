/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

const calls: { path: string; init?: RequestInit }[] = [];
let view: unknown;
let preview: unknown;
let removeTold = true;
let joinCandidates: unknown[] = [];

vi.mock('../../opscenter/api/auth.svelte', async (original) => ({
  ...(await original<Record<string, unknown>>()),
  authFetch: async (path: string, init?: RequestInit) => {
    calls.push({ path, init });
    const method = init?.method ?? 'GET';
    if (path === '/computers' && method === 'GET') return structuredClone(view);
    if (path === '/computers/invites' && method === 'POST') {
      const live = { id: 'inv1', kind: 'code', code_live: true, expires_at: null, attempts_left: 3 };
      (view as { invites: unknown[] }).invites = [live];
      return { id: 'inv1', code: '123456', link: 'carnivore://join/v1/abc', expires_at: new Date(Date.now() + 14 * 60000 + 30000).toISOString(),
        attempts_left: 3, addresses: ['203.0.113.11'], fid_short: 'ab12cd' };
    }
    if (path === '/computers/add/preview') return preview;
    if (path === '/computers/add') return { job_id: 'job1' };
    if (path.startsWith('/computers/peers/') && method === 'DELETE') return { removed: true, peer_told: removeTold };
    if (path.endsWith('/direction')) return {};
    if (path === '/computers/join') return { state: 'finding', error: null, main_label: null, candidates: joinCandidates };
    if (path === '/computers/leave') return { left: true, main_told: true };
    return {};
  },
}));

import { auth } from '../../opscenter/api/auth.svelte';
import ComputersPanel from './ComputersPanel.svelte';
import { activity, computers, join, stopJoinPoll } from './computers-store.svelte';
import { setLocale } from '../i18n/index.svelte';

setLocale('en');

const SELF = { install_id: 'me', label: 'studio', fid_short: 'ab12cd', role: 'main',
  link: { state: 'listening', port: 8443, join_open: false, addresses: [], code_paused_until: null }, main: null };

function computer(id: string, over: Record<string, unknown> = {}) {
  return { install_id: id, label: id, host_key: null, transport: 'tls', role: 'member', state: 'connected', direction: 'both', fid: `${id}fid000`,
    fid_short: `${id}fid`.slice(0, 6), cert_sha256: null, joined_at: null, last_link_at: new Date().toISOString(), possible_duplicate_of: null, ...over };
}

const mounted: ReturnType<typeof mount>[] = [];
async function render(over: Record<string, unknown> = {}): Promise<HTMLElement> {
  view = { self: SELF, computers: [computer('laptop'), computer('hosta', { transport: 'ssh', direction: 'one_way', state: 'disconnected' })],
    invites: [], add_jobs: [], ...over };
  const target = document.createElement('div');
  document.body.append(target);
  mounted.push(mount(ComputersPanel, { target, props: {} }));
  await computers.refresh(true);
  flushSync();
  return target;
}

async function settle(): Promise<void> {
  await new Promise((r) => setTimeout(r, 0));
  await new Promise((r) => setTimeout(r, 0));
  flushSync();
}

beforeEach(() => {
  auth.state = 'signed-in';
  calls.length = 0;
  preview = null;
  removeTold = true;
  Object.assign(activity, { busy: null, error: null, invite: null, inviteSeen: false, notTold: null, preview: null, join: null });
});
afterEach(async () => {
  stopJoinPoll();
  for (const c of mounted.splice(0)) await unmount(c);
  document.body.replaceChildren();
});

describe('the computers panel on a main', () => {
  test('lists each computer with its link, state and the one way note, and no join form', async () => {
    const root = await render();
    expect(root.querySelector('[data-computer="laptop"] [data-cmp="transport"]')).toBeNull();
    expect(root.querySelector('[data-computer="laptop"] [data-mark="link"]')!.getAttribute('data-link')).toBe('linked');
    expect(root.querySelector('[data-computer="hosta"] [data-cmp="transport"]')!.textContent).toBe('over ssh');
    expect(root.querySelector('[data-computer="hosta"] [data-mark="link"]')!.getAttribute('aria-label')).toBe('link down');
    expect(root.querySelector('[data-computer="laptop"] [data-cmp="one-way"]')).toBeNull();
    expect(root.querySelector('[data-computer="hosta"] [data-cmp="one-way"]')!.textContent).toContain('hosta cannot change anything here');
    expect(root.querySelector('[data-cmp="join"]')).toBeNull();
  });

  test('add a computer mints an invite and shows the code as 123 456 with its countdown, attempts and link', async () => {
    const root = await render();
    root.querySelector<HTMLButtonElement>('[data-cmp="add"]')!.click();
    await settle();
    expect(calls.some((c) => c.path === '/computers/invites' && c.init?.method === 'POST')).toBe(true);
    expect(root.querySelector('[data-cmp="code"]')!.textContent).toBe('123 456');
    expect(root.querySelector('[data-cmp="countdown"]')!.textContent).toMatch(/^expires in 14:\d\d$/);
    expect(root.querySelector('[data-cmp="attempts"]')!.textContent).toBe('attempts left 3');
    expect(root.querySelector('[data-cmp="link"]')!.textContent).toBe('carnivore://join/v1/abc');
    expect(root.querySelector('[data-cmp="self-fid"]')!.textContent).toBe('this computer: ab12cd');
  });

  test('toggling control off sends one_way, and remove asks first and says so when the computer was not told', async () => {
    removeTold = false;
    const root = await render();
    root.querySelector<HTMLButtonElement>('[data-computer="laptop"] [data-cmp="direction"]')!.click();
    await settle();
    const put = calls.find((c) => c.path === '/computers/peers/laptop/direction')!;
    expect(JSON.parse(String(put.init!.body))).toEqual({ direction: 'one_way' });
    root.querySelector<HTMLButtonElement>('[data-computer="laptop"] [data-cmp="remove"]')!.click();
    flushSync();
    expect(calls.some((c) => c.init?.method === 'DELETE')).toBe(false);
    expect(root.querySelector('[data-cmp="remove-confirm"]')!.textContent).toContain('remove laptop?');
    root.querySelector<HTMLButtonElement>('[data-cmp="remove-yes"]')!.click();
    await settle();
    expect(calls.some((c) => c.path === '/computers/peers/laptop' && c.init?.method === 'DELETE')).toBe(true);
    expect(root.querySelector('[data-cmp="not-told"]')!.textContent).toContain('laptop could not be told');
  });

  test('add over ssh: a blocker or a changed key keeps add off, a clean check turns it on and sends the approved key', async () => {
    preview = { host_key_sha256: 'SHA256:abc', known: 'new', reachable: true, auth_ok: true, posix_shell: true, blockers: ['needs_homebrew'] };
    const root = await render();
    const input = root.querySelector<HTMLInputElement>('[data-cmp="ssh-target"]')!;
    input.value = 'me@newbox';
    input.dispatchEvent(new Event('input', { bubbles: true }));
    flushSync();
    root.querySelector<HTMLFormElement>('.cmp-form')!.requestSubmit();
    await settle();
    expect(root.querySelector('[data-cmp="host-key"]')!.textContent).toBe('host key SHA256:abc');
    expect(root.querySelector('[data-blocker="needs_homebrew"]')!.textContent).toContain('homebrew');
    expect(root.querySelector<HTMLButtonElement>('[data-cmp="ssh-add"]')!.disabled).toBe(true);

    preview = { host_key_sha256: 'SHA256:abc', known: 'changed', reachable: true, auth_ok: true, posix_shell: true, blockers: [] };
    root.querySelector<HTMLFormElement>('.cmp-form')!.requestSubmit();
    await settle();
    expect(root.querySelector('[data-cmp="known"]')!.textContent).toBe('this host key changed. not adding.');
    expect(root.querySelector<HTMLButtonElement>('[data-cmp="ssh-add"]')!.disabled).toBe(true);

    preview = { host_key_sha256: 'SHA256:abc', known: 'new', reachable: true, auth_ok: true, posix_shell: true, blockers: [] };
    root.querySelector<HTMLFormElement>('.cmp-form')!.requestSubmit();
    await settle();
    const add = root.querySelector<HTMLButtonElement>('[data-cmp="ssh-add"]')!;
    expect(add.disabled).toBe(false);
    add.click();
    await settle();
    const sent = calls.find((c) => c.path === '/computers/add')!;
    expect(JSON.parse(String(sent.init!.body))).toEqual({ ssh_target: 'me@newbox', host_key_sha256: 'SHA256:abc' });
  });

  test('a running add job shows its steps, with the finished ones marked, and its error in words', async () => {
    const job = { id: 'j1', target: 'me@newbox', host_key_sha256: 'x', state: 'failed', step: 'download', error: 'checksum_mismatch',
      started_at: null, finished_at: null, computer: null };
    const root = await render({ add_jobs: [job] });
    expect(root.querySelector('[data-step="connecting"]')!.getAttribute('data-done')).toBe('true');
    expect(root.querySelector('[data-step="download"]')!.getAttribute('data-now')).toBe('false');
    expect(root.querySelector('[data-cmp="job-error"]')!.textContent).toContain('did not match its checksum');
  });
});

describe('the computers panel elsewhere', () => {
  test('a member sees only its pack line and leave pack (asked first), and no add button', async () => {
    const root = await render({
      self: { ...SELF, role: 'member', main: { label: 'studio', state: 'connected', last_link_at: new Date().toISOString(), reachable_note: false } },
      computers: [computer('studio', { role: 'main' })],
    });
    expect(root.querySelector('[data-cmp="member-line"]')!.textContent).toBe("this computer joined studio's pack");
    expect(root.querySelector('[data-cmp="add"]')).toBeNull();
    expect(root.querySelector('[data-cmp="list"]')).toBeNull();
    root.querySelector<HTMLButtonElement>('[data-cmp="leave"]')!.click();
    flushSync();
    expect(calls.some((c) => c.path === '/computers/leave')).toBe(false);
    expect(root.querySelector('[data-cmp="leave-confirm"]')!.textContent).toContain("leave studio's pack?");
    root.querySelector<HTMLButtonElement>('[data-cmp="leave-yes"]')!.click();
    await settle();
    expect(calls.some((c) => c.path === '/computers/leave' && c.init?.method === 'POST')).toBe(true);
  });

  test('a standalone computer can join a pack with a typed code; the code is sent without its space', async () => {
    const root = await render({ self: { ...SELF, role: 'standalone' }, computers: [] });
    expect(root.querySelector('[data-cmp="join-warning"]')!.textContent).toContain('authenticator stops working');
    const input = root.querySelector<HTMLInputElement>('[data-cmp="join-input"]')!;
    input.value = '123 456';
    input.dispatchEvent(new Event('input', { bubbles: true }));
    flushSync();
    root.querySelector<HTMLButtonElement>('[data-cmp="join-go"]')!.click();
    await settle();
    const sent = calls.find((c) => c.path === '/computers/join' && c.init?.method === 'POST')!;
    expect(JSON.parse(String(sent.init!.body))).toEqual({ code: '123456' });
    expect(root.querySelector('[data-cmp="join-step"]')!.textContent).toBe('finding your pack');
  });

  test('the join poll stops while several packs wait for a pick, and keeps going for one (P8)', async () => {
    const reads = () => calls.filter((c) => c.path === '/computers/join' && (c.init?.method ?? 'GET') === 'GET').length;
    for (const [candidates, polls] of [[[{ name: 'a', fid: 'aa', fid_short: 'aa' }, { name: 'b', fid: 'bb', fid_short: 'bb' }], 1], [[], 3]] as const) {
      calls.length = 0;
      joinCandidates = [...candidates];
      await render({ self: { ...SELF, role: 'standalone' }, computers: [] });
      vi.useFakeTimers();
      try {
        await join({ code: '123456' });
        await vi.advanceTimersByTimeAsync(5000);
        if (polls === 1) expect(reads()).toBe(1);
        else expect(reads()).toBeGreaterThan(2);
      } finally {
        vi.useRealTimers();
        stopJoinPoll();
      }
    }
  });
});
