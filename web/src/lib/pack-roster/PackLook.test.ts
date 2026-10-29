/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

const calls: { path: string; init?: RequestInit }[] = [];
let packName: string | null = 'studio pack';
let patchRefuses = false;
const CANDIDATES = [
  { name: 'studio', fid: 'fid-a', fid_short: 'aaaaaa', pack_name: 'studio pack', label: 'studio pack aaaaaa' },
  { name: 'loft', fid: 'fid-b', fid_short: 'bbbbbb', pack_name: null, label: 'loft bbbbbb' },
];

vi.mock('../../opscenter/api/auth.svelte', async (original) => {
  const real = await original<Record<string, unknown> & { ApiError: new (m: string, s: number, c?: string | null, p?: unknown) => Error }>();
  return {
    ...real,
    authFetch: async (path: string, init?: RequestInit) => {
      calls.push({ path, init });
      const method = init?.method ?? 'GET';
      if (path === '/computers' && method === 'GET') {
        return { self: { install_id: 'me', label: 'studio', fid_short: 'ab12cd', role: 'standalone',
          link: { state: 'listening', port: 8443, join_open: false, addresses: [], code_paused_until: null }, main: null },
          computers: [], invites: [], add_jobs: [] };
      }
      if (path === '/computers/join/look') return { state: 'finding', error: null, main_label: null, candidates: [] };
      if (path === '/computers/join' && method === 'GET') return { state: 'finding', error: null, main_label: null, candidates: CANDIDATES };
      if (path === '/computers/join') return { state: 'connecting', error: null, main_label: null, candidates: [] };
      if (path === '/federation/settings' && method === 'GET') return { advertise: false, pack_name: packName };
      if (path === '/federation/settings' && method === 'PATCH') {
        if (patchRefuses) throw new real.ApiError('bad', 422, 'bad_pack_name', { detail: { code: 'bad_pack_name' } });
        packName = (JSON.parse(String(init?.body)) as { pack_name: string | null }).pack_name;
        return { advertise: false, pack_name: packName };
      }
      return {};
    },
  };
});

import { auth } from '../../opscenter/api/auth.svelte';
import RosterJoin from './RosterJoin.svelte';
import SettingsPanel from './SettingsPanel.svelte';
import { activity, computers, stopJoinPoll } from '../computers/computers-store.svelte';
import { setLocale } from '../i18n/index.svelte';

setLocale('en');
const mounted: ReturnType<typeof mount>[] = [];

async function settle(ms = 0): Promise<void> {
  await new Promise((r) => setTimeout(r, ms));
  await new Promise((r) => setTimeout(r, 0));
  flushSync();
}
async function render(component: typeof RosterJoin | typeof SettingsPanel, props: Record<string, unknown> = {}): Promise<HTMLElement> {
  const target = document.createElement('div');
  document.body.append(target);
  mounted.push(mount(component as typeof RosterJoin, { target, props: props as Record<string, never> }));
  await computers.refresh(true);
  await settle();
  return target;
}

beforeEach(() => {
  auth.state = 'signed-in';
  calls.length = 0;
  packName = 'studio pack';
  patchRefuses = false;
  Object.assign(activity, { busy: null, error: null, invite: null, inviteSeen: false, notTold: null, preview: null, join: null, looking: false });
});
afterEach(async () => {
  stopJoinPoll();
  for (const c of mounted.splice(0)) await unmount(c);
  document.body.replaceChildren();
});

describe('look for a pack in the join form', () => {
  test('look posts, two packs show as rows, no hides one, yes keeps the fid and the join sends it', async () => {
    const root = await render(RosterJoin);
    root.querySelector<HTMLButtonElement>('[data-cmp="look"]')!.click();
    await settle();
    expect(calls.some((c) => c.path === '/computers/join/look' && c.init?.method === 'POST')).toBe(true);
    await settle(1100);
    const rows = () => [...root.querySelectorAll('[data-cmp="offer"]')];
    expect(rows().map((r) => r.querySelector('p')!.textContent)).toEqual(['join studio pack aaaaaa?', 'join loft bbbbbb?']);
    expect(root.querySelector('[data-cmp="join-pick"]')).toBeNull();
    rows()[0]!.querySelector<HTMLButtonElement>('[data-cmp="offer-no"]')!.click();
    await settle();
    expect(rows().map((r) => r.querySelector('p')!.textContent)).toEqual(['join loft bbbbbb?']);
    rows()[0]!.querySelector<HTMLButtonElement>('[data-cmp="offer-yes"]')!.click();
    await settle();
    const input = root.querySelector<HTMLInputElement>('[data-cmp="join-input"]')!;
    expect(document.activeElement).toBe(input);
    input.value = '123 456';
    input.dispatchEvent(new Event('input', { bubbles: true }));
    flushSync();
    root.querySelector<HTMLButtonElement>('[data-cmp="join-go"]')!.click();
    await settle();
    const sent = calls.find((c) => c.path === '/computers/join' && c.init?.method === 'POST')!;
    expect(JSON.parse(String(sent.init!.body))).toEqual({ code: '123456', candidate_fid: 'fid-b' });
  });
});

describe('the pack name field', () => {
  const panel = () => render(SettingsPanel, { onClose: () => undefined, nowMs: Date.now() });

  test('shows the stored name, and PATCHes the trimmed value', async () => {
    const root = await panel();
    const input = root.querySelector<HTMLInputElement>('[data-cmp="pack-name-input"]')!;
    expect(input.value).toBe('studio pack');
    input.value = '  loft pack  ';
    input.dispatchEvent(new Event('input', { bubbles: true }));
    flushSync();
    root.querySelector<HTMLButtonElement>('[data-cmp="pack-name-save"]')!.click();
    await settle();
    const sent = calls.find((c) => c.path === '/federation/settings' && c.init?.method === 'PATCH')!;
    expect(JSON.parse(String(sent.init!.body))).toEqual({ pack_name: 'loft pack' });
  });

  test('shows the server refusal as an inline line', async () => {
    patchRefuses = true;
    const root = await panel();
    const input = root.querySelector<HTMLInputElement>('[data-cmp="pack-name-input"]')!;
    input.value = 'bad!';
    input.dispatchEvent(new Event('input', { bubbles: true }));
    flushSync();
    root.querySelector<HTMLButtonElement>('[data-cmp="pack-name-save"]')!.click();
    await settle();
    expect(root.querySelector('[role="alert"]')!.textContent).toContain('letters, digits');
  });
});
