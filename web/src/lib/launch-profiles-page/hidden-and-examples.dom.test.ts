/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';
import LaunchProfilesScreen from './LaunchProfilesScreen.svelte';
import { createLaunchProfilesApi, type ProfileList } from './api';
import { setLocale } from '../i18n/index.svelte';

setLocale('en');

const row = (id: string, harness: string, installed: boolean) => ({
    id, label: id, harness, icon: null, description: null, default: false,
    account: { mode: 'follow_active', account_id: null }, endpoint: { mode: 'native', connection_id: null },
    model: { mode: 'default', value: null }, permissions: 'harness_default', flags: [], env: [], secrets: [],
    shell_profile: false, before_launch: null, custom_command: null, custom_command_ack_no_args: false,
    summary: { model: 'default', permissions_badge: '', account: 'follow', endpoint: 'native' }, installed,
});
const profiles = { revision: 1, profiles: [row('claude-default', 'claude', true), row('codex-default', 'codex', false)] } as unknown as ProfileList;

let handle: Record<string, unknown> | null = null;
const settle = async (): Promise<void> => { for (let i = 0; i < 8; i += 1) await Promise.resolve(); await tick(); flushSync(); };

async function mountScreen(): Promise<HTMLElement> {
    const target = document.createElement('div');
    document.body.append(target);
    const api = createLaunchProfilesApi(async () => profiles as never);
    handle = mount(LaunchProfilesScreen, { target, props: { embedded: true, api } }) as Record<string, unknown>;
    await settle();
    return target;
}

beforeEach(() => { vi.stubGlobal('fetch', vi.fn(async () => new Response('[]', { status: 200 }))); });
afterEach(() => { vi.unstubAllGlobals(); if (handle) unmount(handle); handle = null; document.body.innerHTML = ''; });

test('an uninstalled agent default is hidden, and show hidden brings it back marked not installed', async () => {
    const target = await mountScreen();
    expect(target.querySelector('[data-lp-row="claude-default"]')).not.toBeNull();
    expect(target.querySelector('[data-lp-row="codex-default"]')).toBeNull();
    const toggle = target.querySelector<HTMLInputElement>('[data-lp-show-hidden]')!;
    expect(toggle).not.toBeNull();
    toggle.click();
    await settle();
    expect(target.querySelector('[data-lp-row="codex-default"]')).not.toBeNull();
    expect(target.querySelector('[data-lp-not-installed]')).not.toBeNull();
});

test('with nothing hidden there is no show hidden switch', async () => {
    const target = document.createElement('div');
    document.body.append(target);
    const all = { revision: 1, profiles: [row('claude-default', 'claude', true)] } as unknown as ProfileList;
    handle = mount(LaunchProfilesScreen, { target, props: { embedded: true, api: createLaunchProfilesApi(async () => all as never) } }) as Record<string, unknown>;
    await settle();
    expect(target.querySelector('[data-lp-hidden]')).toBeNull();
});

test('the new-profile screen has the examples folded, hints on the three fields, and an example fills the form', async () => {
    const target = await mountScreen();
    target.querySelector<HTMLButtonElement>('[data-lp-new]')!.click();
    await settle();
    target.querySelector<HTMLButtonElement>('[data-lp-template="claude_subscription"]')!.click();
    await settle();
    const examples = target.querySelector('[data-lp-examples]')!;
    expect(examples).not.toBeNull();
    expect(examples.querySelector('.oc-fold__toggle')!.getAttribute('aria-expanded')).toBe('false');
    expect(target.querySelector('#lp-harness-help, [id$="lp-harness-help"]')).not.toBeNull();
    expect(target.querySelector('#lp-model-mode-help')).not.toBeNull();
    expect(target.querySelector('[data-lp-perms-hint]')).not.toBeNull();
    (examples.querySelector('.oc-fold__toggle') as HTMLElement).click();
    await settle();
    target.querySelector<HTMLButtonElement>('[data-lp-example-use="claude_model"]')!.click();
    await settle();
    expect((target.querySelector('#lp-model-value') as HTMLInputElement).value).toBe('sonnet');
    expect((target.querySelector('#lp-flags') as HTMLTextAreaElement).value).toBe('--verbose');
});
