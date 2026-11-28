/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

const events: string[] = [];
const calls: { path: string; method: string }[] = [];
let walk: Record<string, unknown>;
let startFails = false;

vi.mock('../../opscenter/api/auth.svelte', async (original) => ({
  ...(await original<Record<string, unknown>>()),
  authFetch: async (path: string, init?: RequestInit) => {
    const method = init?.method ?? 'GET';
    calls.push({ path, method });
    if (path === '/pack/rotate') return structuredClone(walk);
    if (path === '/pack/rotate/start') {
      events.push('start');
      if (startFails) { const { ApiError } = await original<{ ApiError: new (...a: unknown[]) => Error }>(); throw new ApiError('start refused here', 409, { code: 'rotate_terminal_only' }); }
      return { account: 'work', started_at: 1, sign_in_seen: 'not_seen' };
    }
    if (path === '/pack/rotate/argent') return { computers: [{ install_id: 'abcdef0123456789', state: 'dead' }] };
    return {};
  },
}));
vi.mock('../ledger/ledger-host', () => ({
  browserLedgerHost: () => ({
    loginProviderAccount: async (id: string) => { events.push('login:' + id); return { session_id: 'ses_1', device_auth: false }; },
    openSession: async (id: string) => { events.push('open:' + id); },
  }),
}));

import { setLocale } from '../i18n/index.svelte';
import RotateWalk from './RotateWalk.svelte';

setLocale('en');
const NOW = Date.parse('2026-11-22T12:00:00Z');
const copy = (status: string, over: Record<string, unknown> = {}) => ({ install_id: 'abcdef0123456789', status, expires_at: null, killed_at: null, ended_by: null, ...over });
const acct = (over: Record<string, unknown> = {}) => ({ account: 'work', name: 'work', provider: 'claude', sign_in: 'app', started_at: null, sign_in_seen: 'not_started', sign_in_ends: 'unknown', copies: [copy('dies_by', { expires_at: NOW + 3_600_000 })], ...over });
const base = () => ({ accounts: [acct()], argent: { known: true, copies: [] }, removed_computers: 1, unlisted: [], not_tracked: [] });

const mounted: ReturnType<typeof mount>[] = [];
async function render(openIt = true): Promise<HTMLElement> {
  const target = document.createElement('div');
  document.body.append(target);
  mounted.push(mount(RotateWalk, { target, props: { nowMs: NOW } }));
  await settle();
  if (openIt) { (target.querySelector('[data-act="rotate-open"]') as HTMLElement).click(); await settle(); }
  return target;
}
/** Let promises settle and Svelte paint. */
async function settle(): Promise<void> {
  for (let i = 0; i < 6; i++) await new Promise((r) => setTimeout(r, 0));
  flushSync();
}

beforeEach(() => { events.length = 0; calls.length = 0; startFails = false; walk = base(); });
afterEach(async () => { for (const c of mounted.splice(0)) await unmount(c); document.body.replaceChildren(); });

describe('rotate everything', () => {
  test('closed it is one button and reads nothing', async () => {
    const root = await render(false);
    expect(root.querySelector('[data-act="rotate-open"]')?.textContent).toContain('rotate everything');
    expect(calls).toEqual([]);
    expect(root.querySelector('[data-rotate-account]')).toBeNull();
  });

  test('sign in again records the start first, then opens the existing sign-in', async () => {
    const root = await render();
    expect(calls.map((c) => c.path)).toEqual(['/pack/rotate']);
    (root.querySelector('[data-act="rotate-sign-in"]') as HTMLElement).click();
    await settle();
    expect(events).toEqual(['start', 'login:work', 'open:ses_1']);
    expect(calls.find((c) => c.path === '/pack/rotate/start')?.method).toBe('POST');
  });

  test('a removed computer shows the name the alpha signed, or its id prefix when none was kept', async () => {
    walk = { ...base(), accounts: [acct({ copies: [copy('dies_by', { label: 'laptop' }), copy('dies_by', { install_id: 'ffff000011112222' })] })] };
    const root = await render();
    const rows = [...root.querySelectorAll('[data-copy]')].map((r) => r.textContent ?? '');
    expect(rows[0]).toContain('removed computer laptop');
    expect(rows[1]).toContain('removed computer ffff0000');
  });

  test('a refused start shows its sentence and opens no sign-in', async () => {
    startFails = true;
    const root = await render();
    (root.querySelector('[data-act="rotate-sign-in"]') as HTMLElement).click();
    await settle();
    expect(events).toEqual(['start']);
    expect(root.querySelector('[data-notice]')?.textContent).toContain('start refused here');
  });

  test('the default claude login gets words and no button', async () => {
    walk = { ...base(), accounts: [acct({ account: 'auto-claude-default', sign_in: 'terminal', copies: [] })] };
    const root = await render();
    expect(root.querySelector('[data-act="rotate-sign-in"]')).toBeNull();
    expect(root.textContent).toContain('claude auth login');
  });

  test('the cancel shows only while an argent copy can still be cancelled, and posts', async () => {
    walk = { ...base(), argent: { known: true, copies: [copy('dead_now', { killed_at: NOW - 1000, ended_by: 'argent_204' })] } };
    let root = await render();
    expect(root.querySelector('[data-act="rotate-argent"]')).toBeNull();
    expect(root.querySelector('[data-rotate-argent]')?.textContent).toContain('dead now');
    await unmount(mounted.pop()!); document.body.replaceChildren();
    walk = { ...base(), argent: { known: true, copies: [copy('dies_by', { expires_at: NOW + 3_600_000 })] } };
    root = await render();
    (root.querySelector('[data-act="rotate-argent"]') as HTMLElement).click();
    await settle();
    expect(calls.some((c) => c.path === '/pack/rotate/argent' && c.method === 'POST')).toBe(true);
    expect(root.querySelector('[data-cancelled]')?.textContent).toContain('cancelled at argent');
  });

  test('github is words and a link, never a button, and shows only when the server names it', async () => {
    let root = await render();
    expect(root.querySelector('[data-rotate-github]')).toBeNull();
    await unmount(mounted.pop()!); document.body.replaceChildren();
    walk = { ...base(), not_tracked: ['github'] };
    root = await render();
    const gh = root.querySelector('[data-rotate-github]')!;
    expect(gh.querySelector('button')).toBeNull();
    const a = gh.querySelector('a')!;
    expect(a.getAttribute('href')).toBe('https://github.com/settings/applications');
    expect(a.getAttribute('rel')).toBe('noopener noreferrer');
    expect(gh.textContent).toContain('every computer');
  });

  test('dead now shows only where the server said dead_now, and a lapsed dies_by reads ran out', async () => {
    walk = { ...base(), accounts: [acct({ copies: [copy('dies_by', { expires_at: NOW + 3_600_000 }), copy('dies_by', { expires_at: NOW - 3_600_000 }), copy('expiry_unknown')] })] };
    const root = await render();
    const text = root.querySelector('[data-rotate-account]')!.textContent!;
    expect(text).not.toContain('dead now');
    expect(text).toContain('dies by');
    expect(text).toContain('ran out');
    expect(text).toContain('not known to end copies already sent');
  });

  test('copies of an account this computer cannot sign in are shown, marked, with no button', async () => {
    walk = { ...base(), accounts: [], unlisted: [{ account: 'gone-acct', provider: 'codex', copies: [copy('expiry_unknown')] }] };
    const root = await render();
    const row = root.querySelector('[data-rotate-unlisted="gone-acct"]')!;
    expect(row.querySelector('button')).toBeNull();
    expect(row.textContent).toContain('no account with this id');
  });
});

describe('the provider word beside an account name', () => {
  test('shows unless the name already says it as a whole word', async () => {
    walk = { ...base(), accounts: [acct({ account: 'a', name: 'work' }), acct({ account: 'b', name: 'my claude' }), acct({ account: 'c', name: 'claudette' })] };
    const root = await render();
    const dim = (id: string): string => root.querySelector(`[data-rotate-account="${id}"] li:first-child .pp-dim`)?.textContent ?? '';
    expect(dim('a')).toBe('claude');
    expect(dim('b')).toBe('');
    expect(dim('c')).toBe('claude');
  });
});
