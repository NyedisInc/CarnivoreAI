/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

import SettingsScreen from './SettingsScreen.svelte';
import { settingsInGroup } from './settings-registry';
import { settingsDoc } from './settings-doc.svelte';
import { settingsView } from './settings-view.svelte';
import { autoSleep } from '../auto-sleep/auto-sleep-store.svelte';
import { setLocale } from '../i18n/index.svelte';

setLocale('en');

function isInert(el: HTMLElement): boolean {
    return (el as HTMLElement & { inert?: boolean }).inert === true || el.hasAttribute('inert');
}

let handle: Record<string, unknown> | null = null;

async function settle(): Promise<void> {
    for (let i = 0; i < 6; i += 1) await Promise.resolve();
    await tick();
    flushSync();
}

const autoSleepState = { enabled: true, idle_minutes: 60, min_idle_minutes: 5, max_idle_minutes: 10080, unread_blocks_sleep: false, unread_idle_minutes: 180, keep_awake: [], keep_awake_session_uuids: [], mac_awake: false };

const statsState = { enabled: false, revision: 1, db_bytes: 2048, clear: { state: 'idle', phase: '', bytes_before: null, bytes_after: null, reclaimed_bytes: null, error: '' }, backfill: { state: 'idle', pending_sources: 0, known_sources: 0 } };

function answer(url: string): Response {
    if (url.includes('/auto-sleep')) return new Response(JSON.stringify(autoSleepState), { status: 200 });
    if (url.includes('/stats/maintenance')) return new Response(JSON.stringify(statsState), { status: 200 });
    if (url.includes('/launch-profiles')) return new Response(JSON.stringify({ profiles: [], revision: 0 }), { status: 200 });
    return new Response(JSON.stringify({ workspace: {}, server_prefs: {}, server: {}, notifications: {} }), { status: 200 });
}

function mountPage(): HTMLElement {
    const target = document.createElement('div');
    document.body.append(target);
    handle = mount(SettingsScreen, { target, props: { embedded: true } }) as Record<string, unknown>;
    flushSync();
    return target;
}

beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => answer(String(input))));
    settingsDoc.discard();
    window.location.hash = '#settings/sessions/agents';
});

afterEach(() => {
    if (handle) unmount(handle);
    handle = null;
    settingsDoc.discard();
    document.body.innerHTML = '';
    window.location.hash = '';
    vi.unstubAllGlobals();
});

test('a deep link opens the named tab with only that group, and a draft on another tab keeps the bar, the dots and the name', async () => {
    const root = mountPage();
    (handle as unknown as { show(): void }).show();
    await settle();

    const selected = root.querySelector<HTMLElement>('.oc-ptab[aria-selected="true"]')!;
    expect(selected.dataset.tab).toBe('agents');
    const ids = [...root.querySelectorAll<HTMLElement>('[data-setting-id]')].map((el) => el.dataset.settingId);
    expect(ids).toEqual(settingsInGroup('sessions.agents').map((s) => s.id));
    expect([...root.querySelectorAll('.oc-ptab')].map((el) => el.textContent!.trim())).toEqual([
        'auto-sleep',
        'agents',
    ]);
    expect(root.querySelector('.st-footer')).toBeNull();

    settingsView.setTab('sessions', 'auto_sleep');
    await settle();
    settingsDoc.setDraft('auto_sleep_minutes', 30);
    await settle();
    root.querySelector<HTMLButtonElement>('.oc-ptab[data-tab="agents"]')!.click();
    await settle();

    expect(root.querySelector('.oc-ptab[aria-selected="true"]')!.getAttribute('data-tab')).toBe('agents');
    expect(root.querySelector('.oc-ptab[data-tab="auto_sleep"] .oc-ptab__dot')).not.toBeNull();
    expect(root.querySelector('.oc-ptab[data-tab="agents"] .oc-ptab__dot')).toBeNull();
    expect(root.querySelector('.st-nav button[data-section="sessions"] .oc-ptab__dot')).not.toBeNull();
    expect(root.querySelector('.st-footer')).toBeNull();
    root.querySelector<HTMLButtonElement>('.oc-ptab[data-tab="auto_sleep"]')!.click();
    await settle();
    expect(root.querySelector('.oc-ptab[aria-selected="true"]')!.getAttribute('data-tab')).toBe('auto_sleep');
    expect(root.querySelector('.st-footer')).not.toBeNull();
});

test('appearance has five tabs and no header shortcuts; a one-group section has no strip', async () => {
    const root = mountPage();
    await settle();
    root.querySelector<HTMLButtonElement>('.st-nav button[data-section="appearance"]')!.click();
    await settle();
    expect([...root.querySelectorAll('.oc-ptab')].map((el) => (el as HTMLElement).dataset.tab)).toEqual([
        'colors',
        'sidebar',
        'status_bar',
        'control_center',
        'motion',
    ]);
    expect(root.textContent).not.toContain('header shortcuts');

    root.querySelector<HTMLButtonElement>('.st-nav button[data-section="log_processor"]')!.click();
    await settle();
    expect(root.querySelector('.oc-ptabs')).toBeNull();
    expect(root.querySelector('.st-group')).not.toBeNull();
});

test('launch profiles embeds its screen inset: no second title bar, and a search for shortcuts finds the keys section', async () => {
    const root = mountPage();
    await settle();
    root.querySelector<HTMLButtonElement>('.st-nav button[data-section="launch_profiles"]')!.click();
    await settle();
    const inner = root.querySelector('.st-screen[data-screen="launch-profiles"]')!;
    expect(inner.querySelector('.oc-page--inset')).not.toBeNull();
    expect(inner.querySelector('.oc-titlebar')).toBeNull();
    expect(root.querySelectorAll('.oc-titlebar').length).toBe(1);
    expect(inner.querySelector('[data-lp-new]')).not.toBeNull();

    const search = root.querySelector<HTMLInputElement>('.st-nav input[type="search"]')!;
    search.value = 'hotkeys';
    search.dispatchEvent(new Event('input', { bubbles: true }));
    await settle();
    expect(root.querySelector('[data-hit-section="keys"]')).not.toBeNull();
});

test('keyboard shortcuts embeds its screen inset: one title bar, the shortcuts listed', async () => {
    const root = mountPage();
    await settle();
    root.querySelector<HTMLButtonElement>('.st-nav button[data-section="keys"]')!.click();
    await settle();
    const inner = root.querySelector('.st-screen[data-screen="keys"]')!;
    expect(inner.querySelector('.oc-titlebar')).toBeNull();
    expect(root.querySelectorAll('.oc-titlebar').length).toBe(1);
    expect(inner.textContent?.length ?? 0).toBeGreaterThan(40);
});

test('rows render in one column inside one frame; the footer save is dimmed until a draft, then saves; a nested row is inert while its parent is off', async () => {
    window.location.hash = '#settings/sessions/auto_sleep';
    const root = mountPage();
    (handle as unknown as { show(): void }).show();
    await settle();
    await settle();

    const frames = root.querySelectorAll('[data-st-frame]');
    expect(frames).toHaveLength(1);
    const rows = [...frames[0]!.querySelectorAll<HTMLElement>('.st-rows > .st-row')];
    expect(rows.map((r) => r.dataset.settingId)).toEqual(settingsInGroup('sessions.auto_sleep').map((s) => s.id));
    for (const row of rows) {
        const [first, second] = [...row.children].filter((c) => c.tagName === 'DIV');
        expect(first!.classList.contains('st-row__text'), row.dataset.settingId).toBe(true);
        expect(second!.classList.contains('st-row__control'), row.dataset.settingId).toBe(true);
        expect(row.querySelector('.st-row__control .st-row__help'), row.dataset.settingId).toBeNull();
    }
    const minutes = root.querySelector<HTMLElement>('[data-setting-id="auto_sleep_minutes"]')!;
    expect(minutes.querySelector('.st-unit__suffix')!.textContent).toBe('min');
    expect(minutes.querySelector('.st-row__text .st-row__note')!.textContent).toBe('5 to 10,080 minutes');

    const save = root.querySelector<HTMLButtonElement>('.st-footer [data-settings-save]')!;
    expect(save.disabled).toBe(true);
    const input = root.querySelector<HTMLInputElement>('#setting-input-auto_sleep_minutes')!;
    input.value = '90';
    input.dispatchEvent(new Event('input', { bubbles: true }));
    await settle();
    expect(save.disabled).toBe(false);
    const fetchMock = vi.mocked(fetch);
    save.click();
    await settle();
    await settle();
    expect(fetchMock.mock.calls.some(([url, init]) => String(url).includes('/auto-sleep') && (init as RequestInit | undefined)?.method === 'PUT')).toBe(true);
    expect(save.disabled).toBe(true);

    expect(minutes.classList.contains('st-row--child')).toBe(true);
    expect(isInert(minutes)).toBe(false);
    autoSleepState.enabled = false;
    await autoSleep.refresh(true);
    await settle();
    expect(isInert(minutes)).toBe(true);
    expect(minutes.classList.contains('st-row--off')).toBe(true);
    expect(isInert(root.querySelector<HTMLElement>('[data-setting-id="auto_sleep"]')!)).toBe(false);
    autoSleepState.enabled = true;
});

test('a tab holding a table draws R5 column heads', async () => {
    window.location.hash = '#settings/terminal/startup';
    const root = mountPage();
    (handle as unknown as { show(): void }).show();
    await settle();
    const head = root.querySelector<HTMLElement>('[data-env-head]')!;
    expect(head.classList.contains('oc-colhead')).toBe(true);
    expect([...head.querySelectorAll('.oc-label')].map((el) => el.textContent)).toEqual(['name', 'value']);
    expect(root.querySelectorAll('[data-st-lifecycle]')).toHaveLength(0);
});

test('the agents tab link button reads catalog copy, never its raw key', async () => {
    window.location.hash = '#settings/sessions/agents';
    const root = mountPage();
    (handle as unknown as { show(): void }).show();
    await settle();
    const link = root.querySelector<HTMLButtonElement>('[data-settings-link="open-wrappers"]')!;
    expect(link.textContent!.trim()).toBe('launch profiles ->');
});
