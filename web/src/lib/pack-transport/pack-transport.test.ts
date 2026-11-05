/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount, type Component } from 'svelte';

const calls: { path: string; init?: RequestInit }[] = [];
let publishRefusal: { files: string[]; more: number } | null = null;

vi.mock('../../opscenter/api/auth.svelte', async (original) => ({
  ...(await original<Record<string, unknown>>()),
  authFetch: async (path: string, init?: RequestInit) => {
    calls.push({ path, init });
    if (init?.method === 'POST' && publishRefusal) {
      const { ApiError } = await original<{ ApiError: new (m: string, s: number, c: string | null, p: unknown) => Error }>();
      throw new ApiError('some files could not be opened to check them for a credential. nothing was published.', 409, 'unscannable_files', { detail: { code: 'unscannable_files', files: publishRefusal.files, files_more: publishRefusal.more } });
    }
    if (init?.method === 'POST') return { url: 'https://github.com/NyedisInc/notes', owner: 'NyedisInc', name: 'notes', private: true };
    if (path.endsWith('/replicas')) return { pack_state: 'home', replicas: [] };
    if (path.endsWith('/github-account')) {
      return { air_gap: false, account: null, source: 'none', needs_card: true, rung: 'carried', rung_reason: 'no remote', logged_in: ['NyedisAdam'] };
    }
    return { name: 'notes', private: true, owner: null, account: null, account_source: 'none', asks: ['owner', 'account'], offered: true, reason: null };
  },
}));

import MachineBadge from '../../opscenter/ui/MachineBadge.svelte';
import ProjectTransport from './ProjectTransport.svelte';
import { setLocale } from '../i18n/index.svelte';

setLocale('en');

const mounted: ReturnType<typeof mount>[] = [];
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const place = (component: Component<any>, props: Record<string, unknown>): HTMLElement => {
  const target = document.createElement('div');
  document.body.append(target);
  mounted.push(mount(component, { target, props }));
  flushSync();
  return target;
};
const tick = async (): Promise<void> => { await new Promise((r) => setTimeout(r, 0)); flushSync(); };

afterEach(async () => {
  for (const c of mounted.splice(0)) await unmount(c);
  document.body.replaceChildren();
  calls.length = 0;
  publishRefusal = null;
});

describe('the machine badge', () => {
  test('a remote row wears its computer label and a local one wears nothing', () => {
    const remote = place(MachineBadge, { hostKey: 'peer-abc', label: 'studio', state: 'up' });
    expect(remote.querySelector('[data-machine-badge]')?.textContent).toBe('studio');
    const down = place(MachineBadge, { hostKey: 'peer-abc', label: 'studio', state: 'disconnected' });
    expect(down.querySelector('[data-machine-badge]')?.getAttribute('data-host-state')).toBe('disconnected');
    expect(place(MachineBadge, { hostKey: 'local', label: 'this computer' }).querySelector('[data-machine-badge]')).toBeNull();
    expect(place(MachineBadge, {}).querySelector('[data-machine-badge]')).toBeNull();
  });
});

describe('the publish private repo card', () => {
  test('creates nothing until the owner presses the button, then one POST with what was answered', async () => {
    const root = place(ProjectTransport, { name: 'notes' });
    (root.querySelector('[data-pt="toggle"]') as HTMLElement).click();
    await tick();
    expect(root.querySelector('[data-pt="publish"]')).not.toBeNull();
    expect(root.querySelector('[data-pt="rung-line"]')?.getAttribute('data-rung')).toBe('carried');
    expect(calls.some((c) => c.init?.method === 'POST')).toBe(false);
    const go = root.querySelector('[data-pt="publish-go"]') as HTMLButtonElement;
    expect(go.disabled).toBe(true);
    const ownerBox = root.querySelector('[data-pt="publish-owner-input"]') as HTMLInputElement;
    ownerBox.value = 'NyedisInc';
    ownerBox.dispatchEvent(new Event('input', { bubbles: true }));
    const pick = root.querySelector('[data-pt="publish-account-pick"]') as HTMLSelectElement;
    pick.value = 'NyedisAdam';
    pick.dispatchEvent(new Event('change', { bubbles: true }));
    flushSync();
    expect(go.disabled).toBe(false);
    go.click();
    await tick();
    const posts = calls.filter((c) => c.init?.method === 'POST');
    expect(posts).toHaveLength(1);
    expect(posts[0]!.path).toBe('/projects/notes/publish-repo');
    const body = JSON.parse(String(posts[0]!.init?.body));
    expect(body).toEqual({ owner: 'NyedisInc', account: 'NyedisAdam' });
    expect('private' in body || 'visibility' in body).toBe(false);
    expect(root.querySelector('[data-pt="publish-done"]')?.textContent).toContain('private');
  });
});

describe('a refused publish', () => {
  test('the card names the files the scan refused, capped, with "and N more"', async () => {
    publishRefusal = { files: ['assets/logo.png', 'dump.bin'], more: 3 };
    const root = place(ProjectTransport, { name: 'notes' });
    (root.querySelector('[data-pt="toggle"]') as HTMLElement).click();
    await tick();
    const ownerBox = root.querySelector('[data-pt="publish-owner-input"]') as HTMLInputElement;
    ownerBox.value = 'NyedisInc';
    ownerBox.dispatchEvent(new Event('input', { bubbles: true }));
    const pick = root.querySelector('[data-pt="publish-account-pick"]') as HTMLSelectElement;
    pick.value = 'NyedisAdam';
    pick.dispatchEvent(new Event('change', { bubbles: true }));
    flushSync();
    (root.querySelector('[data-pt="publish-go"]') as HTMLButtonElement).click();
    await vi.waitFor(() => {
      const post = calls.findIndex((c) => c.init?.method === 'POST');
      expect(post).toBeGreaterThan(-1);
      expect(calls.slice(post + 1).some((c) => c.path.endsWith('/publish-repo'))).toBe(true);
    });
    await tick();
    const shown = root.querySelector('[data-pt="error"]')?.textContent ?? '';
    expect(shown).toContain('nothing was published');
    expect(shown).toContain('files: assets/logo.png, dump.bin and 3 more');
  });
});
