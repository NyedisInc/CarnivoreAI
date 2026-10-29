/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

import SettingsScreen from './SettingsScreen.svelte';
import { SETTINGS_SECTIONS, groupsIn, settingsInGroup, isWideControl, settingsIn, slugOf } from './settings-registry';
import { settingsDoc } from './settings-doc.svelte';
import { settingsView } from './settings-view.svelte';
import { tabsOf } from './screen-sections';
import { setLocale } from '../i18n/index.svelte';

setLocale('en');

let handle: Record<string, unknown> | null = null;

async function settle(): Promise<void> {
    for (let i = 0; i < 6; i += 1) await Promise.resolve();
    await tick();
    flushSync();
}

beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ workspace: {}, server_prefs: {}, server: {}, notifications: {} }), { status: 200 })));
    settingsDoc.discard();
    for (const section of SETTINGS_SECTIONS) {
        const first = tabsOf(section.id)[0];
        if (first) settingsView.setTab(section.id, first);
    }
});

afterEach(() => {
    if (handle) unmount(handle);
    handle = null;
    settingsDoc.discard();
    document.body.innerHTML = '';
    vi.unstubAllGlobals();
});

async function open(section: string): Promise<HTMLElement> {
    const target = document.createElement('div');
    document.body.append(target);
    handle = mount(SettingsScreen, { target, props: { embedded: true } }) as Record<string, unknown>;
    flushSync();
    await settle();
    target.querySelector<HTMLButtonElement>(`.st-nav button[data-section="${section}"]`)!.click();
    await settle();
    return target;
}

test('every registry section: one (hidden) section title, a tab per group when it has more than one, and only the open group rendered', async () => {
    for (const section of SETTINGS_SECTIONS.filter((s) => !s.screen)) {
        const root = await open(section.id);
        const groups = groupsIn(section.id);
        expect(root.querySelectorAll('h2.st-section__title').length, section.id).toBe(1);
        expect(root.querySelector('h2.st-section__title')!.classList.contains('oc-visually-hidden'), section.id).toBe(true);
        expect(root.querySelectorAll('.oc-ptab').length, section.id).toBe(groups.length > 1 ? groups.length : 0);
        const drawn = [...root.querySelectorAll<HTMLElement>('.st-group')];
        expect(drawn.map((g) => g.dataset.group), section.id).toEqual([groups[0]]);
        expect(drawn[0]!.querySelector('.st-tabhint')!.textContent!.length, section.id).toBeGreaterThan(0);
        expect(root.querySelector('section.oc-group'), section.id).toBeNull();
        unmount(handle!);
        handle = null;
        document.body.innerHTML = '';
    }
});

test('a row alone in its tab is named by the tab (label kept for assistive tech only); shared groups show each label', async () => {
    const root = await open('appearance');
    root.querySelector<HTMLButtonElement>('.oc-ptab[data-tab="sidebar"]')!.click();
    await settle();
    const solo = root.querySelector('[data-group="appearance.sidebar"] [data-setting-id="row_icons"] .st-row__label');
    expect(solo?.classList.contains('st-row__label--solo')).toBe(true);
    root.querySelector<HTMLButtonElement>('.oc-ptab[data-tab="colors"]')!.click();
    await settle();
    expect(root.querySelector('[data-setting-id="theme"] .st-row__label')?.classList.contains('st-row__label--solo')).toBe(false);
    root.querySelector<HTMLButtonElement>('.oc-ptab[data-tab="status_bar"]')!.click();
    await settle();
    const shared = root.querySelectorAll('[data-group="appearance.status_bar"] .st-row__label');
    expect(shared.length).toBe(settingsInGroup('appearance.status_bar').length);
    shared.forEach((label) => expect(label.classList.contains('st-row__label--solo')).toBe(false));
});

test('panel-sized rows span the group; small controls share its grid', async () => {
    const appearance = await open('appearance');
    for (const def of settingsIn('appearance')) {
        const slug = slugOf(def.group);
        appearance.querySelector<HTMLButtonElement>(`.oc-ptab[data-tab="${slug}"]`)!.click();
        await settle();
        const row = appearance.querySelector(`[data-setting-id="${def.id}"]`)!;
        expect(row.classList.contains('oc-wide'), def.id).toBe(isWideControl(def.control));
        expect(row.classList.contains('oc-wide'), def.id).toBe(def.id !== 'theme');
    }
    unmount(handle!);
    handle = null;
    document.body.innerHTML = '';

    const general = await open('general');
    general.querySelector<HTMLButtonElement>('.oc-ptab[data-tab="paths"]')!.click();
    await settle();
    for (const def of settingsIn('general').filter((d) => d.id !== 'time_zone' && d.id !== 'app_updates')) {
        expect(general.querySelector(`[data-setting-id="${def.id}"]`)!.classList.contains('oc-wide'), def.id).toBe(false);
    }
});

test('on/off settings are the shared square check as a bare switch: the box alone, no on/off word (#1899)', async () => {
    const root = await open('sessions');
    root.querySelector<HTMLButtonElement>('.oc-ptab[data-tab="auto_sleep"]')!.click();
    await settle();
    const sw = root.querySelector<HTMLElement>('[data-setting-id="auto_sleep_unread_blocks"] button.oc-check[role="switch"]');
    expect(sw).not.toBeNull();
    expect(sw!.getAttribute('aria-checked')).not.toBeNull();
    expect(sw!.querySelector('.oc-check__box')).not.toBeNull();
    expect(sw!.classList.contains('oc-check--bare')).toBe(true);
    expect((sw!.textContent ?? '').trim()).toBe('');
    expect((sw!.getAttribute('aria-label') ?? '').length).toBeGreaterThan(0);
});

test('the routing matrix gets the whole pane: its tab carries no side heading column', async () => {
    const root = await open('notifications');
    root.querySelector<HTMLButtonElement>(`.oc-ptab[data-tab="${slugOf('notifications.routing')}"]`)!.click();
    await settle();
    const routing = root.querySelector('[data-group="notifications.routing"]')!;
    expect(routing).not.toBeNull();
    expect(routing.querySelector('[data-setting-id="notification_matrix"]')).not.toBeNull();
    expect(routing.querySelector('.oc-group__side')).toBeNull();
});
