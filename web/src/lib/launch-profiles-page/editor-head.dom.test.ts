/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';
import LaunchProfilesScreen from './LaunchProfilesScreen.svelte';
import { createLaunchProfilesApi, type ProfileList } from './api';
import { setLocale } from '../i18n/index.svelte';

setLocale('en');

const LONG_LABEL = 'a very long launch profile name that used to be squeezed to a few letters beside five tools';

const profiles: ProfileList = {
    revision: 1,
    profiles: [{
        id: 'work', label: LONG_LABEL, harness: 'claude', icon: null, description: null, default: false,
        account: { mode: 'follow_active', account_id: null }, endpoint: { mode: 'native', connection_id: null },
        model: { mode: 'default', value: null }, permissions: 'harness_default', flags: [], env: [], secrets: [],
        shell_profile: false, before_launch: null, custom_command: null, custom_command_ack_no_args: false,
        summary: { model: 'default', permissions_badge: '', account: 'follow', endpoint: 'native' },
    }],
};

let handle: Record<string, unknown> | null = null;

beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('[]', { status: 200 })));
});

afterEach(() => {
    vi.unstubAllGlobals();
    if (handle) unmount(handle);
    handle = null;
    document.body.innerHTML = '';
});

test('the five editor tools live in the card head actions beside the long title', async () => {
    const target = document.createElement('div');
    document.body.append(target);
    const api = createLaunchProfilesApi(async (url: string) => (url.includes('/usage') ? ({ total: 0, counts: {} } as never) : (profiles as never)));
    handle = mount(LaunchProfilesScreen, { target, props: { embedded: true, api } }) as Record<string, unknown>;
    for (let i = 0; i < 6; i += 1) await Promise.resolve();
    await tick();
    target.querySelector<HTMLButtonElement>('[data-lp-row="work"]')!.click();
    for (let i = 0; i < 6; i += 1) await Promise.resolve();
    await tick();
    flushSync();
    const card = target.querySelector('[data-lp-detail]')!;
    const head = card.querySelector('.oc-card__head')!;
    const actions = head.querySelector('.oc-card__actions')!;
    expect(head.textContent).toContain(LONG_LABEL);
    for (const hook of ['check', 'duplicate', 'make-default', 'export', 'delete']) {
        expect(actions.querySelector(`[data-lp-${hook}]`), hook).not.toBeNull();
    }
    expect(card.querySelector('.lp-tools')).toBeNull();
});
