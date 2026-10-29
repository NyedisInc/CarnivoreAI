/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';
import LaunchProfilesScreen from './LaunchProfilesScreen.svelte';
import { createLaunchProfilesApi, type ProfileList } from './api';
import { ApiError } from '../../opscenter/api/auth.svelte';
import { setLocale } from '../i18n/index.svelte';

setLocale('en');

const row = (id: string) => ({
    id, label: id, harness: 'claude', icon: null, description: null, default: false,
    account: { mode: 'follow_active', account_id: null }, endpoint: { mode: 'native', connection_id: null },
    model: { mode: 'default', value: null }, permissions: 'harness_default', flags: [], env: [], secrets: [],
    shell_profile: false, before_launch: null, custom_command: null, custom_command_ack_no_args: false,
    summary: { model: 'default', permissions_badge: '', account: 'follow', endpoint: 'native' },
});
const profiles = { revision: 1, profiles: [row('work'), row('play')] } as unknown as ProfileList;

let handle: Record<string, unknown> | null = null;
let calls: Array<{ method: string; url: string }> = [];
let deleteAnswer: 'ok' | 'in_use' = 'ok';

beforeEach(() => {
    calls = [];
    deleteAnswer = 'ok';
    vi.stubGlobal('fetch', vi.fn(async () => new Response('[]', { status: 200 })));
});
afterEach(() => {
    vi.unstubAllGlobals();
    if (handle) unmount(handle);
    handle = null;
    document.body.innerHTML = '';
});

const settle = async (): Promise<void> => {
    for (let i = 0; i < 8; i += 1) await Promise.resolve();
    await tick();
    flushSync();
};

async function openWork(): Promise<HTMLElement> {
    const target = document.createElement('div');
    document.body.append(target);
    const api = createLaunchProfilesApi((async (url: string, init?: { method?: string }) => {
        calls.push({ method: init?.method ?? 'GET', url });
        if ((init?.method ?? 'GET') === 'DELETE' && deleteAnswer === 'in_use') {
            throw new ApiError('in use', 409, null, { detail: { code: 'in_use', message: 'in use', counts: { sessions: 2 } } });
        }
        if (url.includes('/usage')) return { total: 0, counts: {} };
        if (url.includes('/accounts') || url.includes('/connections')) return [];
        return profiles;
    }) as never);
    handle = mount(LaunchProfilesScreen, { target, props: { embedded: true, api } }) as Record<string, unknown>;
    await settle();
    target.querySelector<HTMLButtonElement>('[data-lp-row="work"]')!.click();
    await settle();
    return target;
}

const deletes = (): number => calls.filter((c) => c.method === 'DELETE').length;

test('the first click on delete sends nothing and offers cancel and a confirm', async () => {
    const target = await openWork();
    target.querySelector<HTMLButtonElement>('[data-lp-delete]')!.click();
    await settle();
    expect(deletes()).toBe(0);
    expect(target.querySelector('[data-lp-delete-confirm]')).not.toBeNull();
    target.querySelector<HTMLButtonElement>('[data-lp-delete-cancel]')!.click();
    await settle();
    expect(deletes()).toBe(0);
    expect(target.querySelector('[data-lp-delete]')).not.toBeNull();
});

test('the confirm sends the delete once', async () => {
    const target = await openWork();
    target.querySelector<HTMLButtonElement>('[data-lp-delete]')!.click();
    await settle();
    target.querySelector<HTMLButtonElement>('[data-lp-delete-confirm]')!.click();
    await settle();
    expect(deletes()).toBe(1);
});

test('move and delete also asks first, naming the target', async () => {
    deleteAnswer = 'in_use';
    const target = await openWork();
    target.querySelector<HTMLButtonElement>('[data-lp-delete]')!.click();
    await settle();
    target.querySelector<HTMLButtonElement>('[data-lp-delete-confirm]')!.click();
    await settle();
    expect(target.querySelector('[data-lp-refusal]')).not.toBeNull();
    const pick = target.querySelector<HTMLSelectElement>('[data-lp-move-to]')!;
    pick.value = 'play';
    pick.dispatchEvent(new Event('change', { bubbles: true }));
    await settle();
    target.querySelector<HTMLButtonElement>('[data-lp-move]')!.click();
    await settle();
    expect(calls.some((c) => c.method === 'POST' && c.url.includes('move'))).toBe(false);
    const confirm = target.querySelector<HTMLButtonElement>('[data-lp-move-confirm]')!;
    expect(confirm.textContent).toContain('play');
});
