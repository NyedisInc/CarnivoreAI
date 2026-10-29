/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';
import { openSettingsLink, openSettingsSection, unmountSettingsScreen, SETTINGS_SCREEN_CONTAINER } from './screen-host';
import { registerSettingsOpener } from './settings-navigate';
import { HIGHLIGHT_CLASS } from './settings-highlight';
import { settingsDoc } from './settings-doc.svelte';
import { settingsView } from './settings-view.svelte';
import { setLocale } from '../i18n/index.svelte';
import RouteRow from '../byoai/RouteRow.svelte';

setLocale('en');

beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ workspace: {}, server_prefs: {}, server: {}, notifications: {} }), { status: 200 })));
    settingsDoc.discard();
    const container = document.createElement('div');
    container.id = SETTINGS_SCREEN_CONTAINER;
    document.body.append(container);
});

afterEach(() => {
    unmountSettingsScreen();
    document.body.innerHTML = '';
    window.location.hash = '';
    settingsDoc.discard();
    vi.unstubAllGlobals();
});

test('openSettingsLink while settings is open lands on the tab and flashes the real control', async () => {
    expect(openSettingsSection('byoai')).toBe(true);
    flushSync();
    expect(settingsView.section).toBe('byoai');
    expect(openSettingsLink('#settings/log_processor/cplugs?highlight=log_processor.cplugs.example')).toBe(true);
    await tick();
    expect(settingsView.section).toBe('log_processor');
    expect(settingsView.tabOf('log_processor')).toBe('cplugs');
    const control = document.createElement('button');
    control.dataset.highlight = 'log_processor.cplugs.example';
    control.scrollIntoView = vi.fn();
    document.body.append(control);
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(control.classList.contains(HIGHLIGHT_CLASS)).toBe(true);
    expect(window.location.hash).toBe('#settings/log_processor/cplugs');
});

test('an old link to the removed ai-for-summaries tab lands on the log processor\'s one real tab', async () => {
    expect(openSettingsSection('byoai')).toBe(true);
    flushSync();
    expect(openSettingsLink('#settings/log_processor/ai?highlight=log_processor.ai.override')).toBe(true);
    await tick();
    expect(settingsView.section).toBe('log_processor');
    expect(settingsView.tabOf('log_processor')).toBe('cplugs');
});

test('a fragment that names no settings section is not opened', () => {
    expect(openSettingsLink('#nope/x')).toBe(false);
    expect(openSettingsLink('#settings/nope?highlight=x')).toBe(false);
});

test('the add-on link on the routing row calls the settings opener with its href and cancels the browser navigation', () => {
    const href = '#settings/log_processor/cplugs?highlight=log_processor.cplugs.example';
    const calls: string[] = [];
    registerSettingsOpener((value) => (calls.push(value), true));
    const target = document.createElement('div');
    document.body.append(target);
    const row = mount(RouteRow, { target, props: { name: 'summaries', href, capability: 'chat', target: null, onSet: () => {}, onClear: () => {} } });
    flushSync();
    const link = target.querySelector<HTMLAnchorElement>('[data-ai="route-owner-link"]');
    const click = new MouseEvent('click', { bubbles: true, cancelable: true });
    link?.dispatchEvent(click);
    expect(calls).toEqual([href]);
    expect(click.defaultPrevented).toBe(true);
    registerSettingsOpener(null);
    const plain = new MouseEvent('click', { bubbles: true, cancelable: true });
    link?.dispatchEvent(plain);
    expect(plain.defaultPrevented).toBe(false);
    unmount(row);
});
