/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';
import SettingsScreen from './SettingsScreen.svelte';
import LaunchProfilesScreen from '../launch-profiles-page/LaunchProfilesScreen.svelte';
import { createLaunchProfilesApi, type ProfileList } from '../launch-profiles-page/api';
import { settingsDoc } from './settings-doc.svelte';
import { isPageDirty, mayClosePage, resetPageDirty, type ConfirmFn } from '../menu-page/menu-page-dirty';
import { setLocale } from '../i18n/index.svelte';

setLocale('en');

let handle: Record<string, unknown> | null = null;

async function settle(): Promise<void> {
    for (let i = 0; i < 6; i += 1) await Promise.resolve();
    await tick();
    flushSync();
}

const profiles: ProfileList = {
    revision: 1,
    profiles: [{
        id: 'work', label: 'work', harness: 'claude', icon: null, description: null, default: false,
        account: { mode: 'follow_active', account_id: null }, endpoint: { mode: 'native', connection_id: null },
        model: { mode: 'default', value: null }, permissions: 'harness_default', flags: [], env: [], secrets: [],
        shell_profile: false, before_launch: null, custom_command: null, custom_command_ack_no_args: false,
        summary: { model: 'default', permissions_badge: '', account: 'follow', endpoint: 'native' },
    }],
};

beforeEach(() => {
    resetPageDirty();
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes('/launch-profiles') && !url.includes('/usage') && !url.includes('/preview')) return new Response(JSON.stringify(profiles), { status: 200 });
        if (url.includes('/usage')) return new Response(JSON.stringify({ total: 0, counts: {} }), { status: 200 });
        if (url.includes('/provider-ledger') || url.includes('/connections')) return new Response('[]', { status: 200 });
        return new Response(JSON.stringify({ workspace: {}, server_prefs: {}, server: {}, notifications: {} }), { status: 200 });
    }));
    settingsDoc.discard();
});

afterEach(() => {
    if (handle) unmount(handle);
    handle = null;
    settingsDoc.discard();
    resetPageDirty();
    document.body.innerHTML = '';
    vi.unstubAllGlobals();
});

test('a setting typed and not yet saved makes the settings page dirty; discarding makes it clean', async () => {
    const target = document.createElement('div');
    document.body.append(target);
    handle = mount(SettingsScreen, { target, props: { embedded: true } }) as Record<string, unknown>;
    await settle();
    expect(isPageDirty('settings')).toBe(false);
    settingsDoc.setDraft('development_root', '/tmp/somewhere');
    expect(isPageDirty('settings')).toBe(true);
    expect(isPageDirty('projects')).toBe(false);
    settingsDoc.discard();
    expect(isPageDirty('settings')).toBe(false);
});

test('confirming "discard and close" drops the drafts the page was holding', async () => {
    const target = document.createElement('div');
    document.body.append(target);
    handle = mount(SettingsScreen, { target, props: { embedded: true } }) as Record<string, unknown>;
    await settle();
    settingsDoc.setDraft('development_root', '/tmp/somewhere');
    const keep: ConfirmFn = async () => false;
    expect(await mayClosePage('settings', keep)).toBe(false);
    expect(settingsDoc.dirtyIds).toEqual(['development_root']);
    const discard: ConfirmFn = async () => true;
    expect(await mayClosePage('settings', discard)).toBe(true);
    expect(settingsDoc.dirtyIds).toEqual([]);
});

test('an edit in the launch profile editor makes the settings page dirty, and opening a profile does not', async () => {
    const target = document.createElement('div');
    document.body.append(target);
    const api = createLaunchProfilesApi(async (url: string) => {
        if (url.includes('/usage')) return { total: 0, counts: {} } as never;
        return profiles as never;
    });
    handle = mount(LaunchProfilesScreen, { target, props: { embedded: true, api } }) as Record<string, unknown>;
    await settle();
    expect(isPageDirty('settings')).toBe(false);
    target.querySelector<HTMLButtonElement>('[data-lp-row="work"]')!.click();
    await settle();
    expect(isPageDirty('settings')).toBe(false);
    const label = target.querySelector<HTMLInputElement>('#lp-label')!;
    label.value = 'work renamed';
    label.dispatchEvent(new Event('input', { bubbles: true }));
    await settle();
    expect(isPageDirty('settings')).toBe(true);
    target.querySelector<HTMLButtonElement>('[data-lp-row="work"]')!.click();
    await settle();
    expect(isPageDirty('settings')).toBe(false);
});
