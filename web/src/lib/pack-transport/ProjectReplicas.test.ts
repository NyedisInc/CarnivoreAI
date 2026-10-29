/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

const calls: { path: string; method: string; body: unknown }[] = [];
const state = vi.hoisted(() => ({ replicas: [] as unknown[], packState: 'home', refuse: null as string | null }));

const machine = (id: string, over: Record<string, unknown> = {}) => ({
  install_id: id, label: id, is_self: false, is_master: false, paired: true, state: 'connected', capabilities: [], specs: null, snapshot: null, age_seconds: 1, ...over,
});

vi.mock('../../opscenter/api/auth.svelte', async (original) => ({
  ...(await original<Record<string, unknown>>()),
  authFetch: async (path: string, init?: RequestInit) => {
    const method = init?.method ?? 'GET';
    calls.push({ path, method, body: init?.body ? JSON.parse(String(init.body)) : null });
    if (path === '/pack/machines') {
      return { master_install_id: 'mac', self_install_id: 'mac', settings: { placement_mode: 'stats', auto_distribute: false }, disagreement: null,
        machines: [machine('mac', { is_self: true, state: 'self' }), machine('studio'), machine('odin'), machine('loki', { state: 'disconnected' })] };
    }
    if (method !== 'GET' && state.refuse) throw new Error(state.refuse);
    if (method === 'POST') state.replicas = [...state.replicas, { install_id: 'studio', label: 'studio', state: 'active' }];
    if (method === 'DELETE') state.replicas = [];
    return { pack_state: state.packState, replicas: state.replicas };
  },
}));

import { auth } from '../../opscenter/api/auth.svelte';
import { packMachines } from '../pack-machines/pack-machines-store.svelte';
import ProjectReplicas from './ProjectReplicas.svelte';
import { setLocale } from '../i18n/index.svelte';

setLocale('en');

const mounted: ReturnType<typeof mount>[] = [];
const settle = async (): Promise<void> => { await new Promise((r) => setTimeout(r, 0)); flushSync(); };
async function render(): Promise<HTMLElement> {
  const target = document.createElement('div');
  document.body.append(target);
  mounted.push(mount(ProjectReplicas, { target, props: { name: 'notes' } }));
  await packMachines.refresh(true);
  await settle();
  return target;
}

beforeEach(() => { auth.state = 'signed-in'; calls.length = 0; state.replicas = []; state.packState = 'home'; state.refuse = null; });
afterEach(async () => {
  for (const c of mounted.splice(0)) await unmount(c);
  document.body.replaceChildren();
});

describe('the project replicas block', () => {
  test('offers only connected paired computers, adds one with a single POST and then lists it', async () => {
    const root = await render();
    expect(root.querySelector('[data-pt="replicas-none"]')).not.toBeNull();
    const options = [...root.querySelectorAll<HTMLOptionElement>('[data-pt="replica-pick"] option')].map((o) => o.value).filter(Boolean);
    expect(options).toEqual(['studio', 'odin']);
    const select = root.querySelector<HTMLSelectElement>('[data-pt="replica-pick"]')!;
    expect(root.querySelector<HTMLButtonElement>('[data-pt="replica-add"]')!.disabled).toBe(true);
    select.value = 'studio';
    select.dispatchEvent(new Event('change', { bubbles: true }));
    flushSync();
    root.querySelector<HTMLButtonElement>('[data-pt="replica-add"]')!.click();
    await settle();
    await settle();
    const post = calls.find((c) => c.method === 'POST');
    expect(post?.path).toBe('/projects/notes/replicas');
    expect(post?.body).toEqual({ machine: 'studio' });
    expect(root.querySelector('[data-replica="studio"]')).not.toBeNull();
    const left = [...root.querySelectorAll<HTMLOptionElement>('[data-pt="replica-pick"] option')].map((o) => o.value).filter(Boolean);
    expect(left).toEqual(['odin']);
  });

  test('remove needs a second press on the danger button, then sends one DELETE', async () => {
    state.replicas = [{ install_id: 'studio', label: 'studio', state: 'active' }];
    const root = await render();
    const button = root.querySelector<HTMLButtonElement>('[data-pt="replica-remove"]')!;
    expect(button.getAttribute('data-btn')).toBe('danger');
    button.click();
    await settle();
    expect(calls.some((c) => c.method === 'DELETE')).toBe(false);
    expect(root.querySelector('[data-pt="replica-remove"]')!.textContent).toContain('press again');
    root.querySelector<HTMLButtonElement>('[data-pt="replica-remove"]')!.click();
    await settle();
    await settle();
    expect(calls.find((c) => c.method === 'DELETE')?.path).toBe('/projects/notes/replicas/studio');
    expect(root.querySelector('[data-replica]')).toBeNull();
  });

  test('a refusal shows in words, and a moved-away project offers no add control', async () => {
    state.refuse = 'studio is set to one way and holds no replicas';
    const root = await render();
    const select = root.querySelector<HTMLSelectElement>('[data-pt="replica-pick"]')!;
    select.value = 'odin';
    select.dispatchEvent(new Event('change', { bubbles: true }));
    flushSync();
    root.querySelector<HTMLButtonElement>('[data-pt="replica-add"]')!.click();
    await settle();
    await settle();
    expect(root.querySelector('[data-pt="replicas-error"]')!.textContent).toContain('holds no replicas');
    await unmount(mounted.pop()!);
    document.body.replaceChildren();
    state.packState = 'moved_away';
    const gone = await render();
    expect(gone.querySelector('[data-pt="replica-add"]')).toBeNull();
  });
});
