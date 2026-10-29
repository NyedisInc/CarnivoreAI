/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

import SettingsScreen from './SettingsScreen.svelte';
import { SETTINGS_SECTIONS } from './settings-registry';
import { settingsHighlightOf, settingsSectionOf, settingsTabOf } from './settings-hash';
import { HIGHLIGHT_CLASS } from './settings-highlight';
import { settingsDoc } from './settings-doc.svelte';
import { settingsView } from './settings-view.svelte';
import { setLocale } from '../i18n/index.svelte';

setLocale('en');

let handle: Record<string, unknown> | null = null;

beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ workspace: {}, server_prefs: {}, server: {}, notifications: {} }), { status: 200 })));
    settingsDoc.discard();
});

afterEach(() => {
    if (handle) unmount(handle);
    handle = null;
    settingsDoc.discard();
    document.body.innerHTML = '';
    window.location.hash = '';
    vi.unstubAllGlobals();
});

test('names a section for every real one, and nothing for anything else', () => {
    for (const section of SETTINGS_SECTIONS) expect(settingsSectionOf(`#settings/${section.id}`)).toBe(section.id);
    expect(settingsSectionOf('settings/appearance')).toBe('appearance');
    for (const bad of ['#settings', '#settings/', '#settings/nope', '#settings/nope/x', '#docs/appearance', '#settings/a/b/c', null, undefined]) {
        expect(settingsSectionOf(bad), String(bad)).toBeNull();
    }
});

test('names a tab as the second segment; an unnamed tab is null, an unknown one is passed on for the caller to drop', () => {
    expect(settingsTabOf('#settings/sessions/agents')).toEqual({ section: 'sessions', tab: 'agents' });
    expect(settingsTabOf('#settings/sessions')).toEqual({ section: 'sessions', tab: null });
    expect(settingsTabOf('settings/hosts')).toBeNull();
    expect(settingsTabOf('#settings/appearance/x')).toEqual({ section: 'appearance', tab: 'x' });
    expect(settingsTabOf('#settings/nope/agents')).toBeNull();
    expect(settingsSectionOf('#settings/sessions/agents')).toBe('sessions');
});

test('show() picks the section the fragment names; a plain #settings keeps the last one', async () => {
    const target = document.createElement('div');
    document.body.append(target);
    handle = mount(SettingsScreen, { target, props: {} }) as Record<string, unknown>;
    settingsView.section = 'general';
    window.location.hash = '#settings/terminal';
    (handle as unknown as { show(): void }).show();
    flushSync();
    await tick();
    expect(settingsView.section).toBe('terminal');
    window.location.hash = '#settings';
    (handle as unknown as { show(): void }).show();
    expect(settingsView.section).toBe('terminal');
});

test('show() applies the tab the fragment names and ignores one the section does not have', async () => {
    const target = document.createElement('div');
    document.body.append(target);
    handle = mount(SettingsScreen, { target, props: {} }) as Record<string, unknown>;
    window.location.hash = '#settings/sessions/agents';
    (handle as unknown as { show(): void }).show();
    flushSync();
    await tick();
    expect(settingsView.section).toBe('sessions');
    expect(settingsView.tabOf('sessions')).toBe('agents');
    window.location.hash = '#settings/sessions/nope';
    (handle as unknown as { show(): void }).show();
    expect(settingsView.tabOf('sessions')).toBe('agents');
});

test('the old #wrappers and #shortcuts fragments name the sections their pages moved into; #hosts names no section (it is the Pack page)', () => {
    expect(settingsTabOf('#wrappers')).toEqual({ section: 'launch_profiles', tab: null });
    expect(settingsTabOf('#launch-profiles')).toEqual({ section: 'launch_profiles', tab: null });
    expect(settingsTabOf('#shortcuts')).toEqual({ section: 'keys', tab: null });
    expect(settingsTabOf('#hosts')).toBeNull();
    expect(settingsTabOf('#settings/plugins')).toBeNull();
});

test('a ?highlight= suffix names a control and leaves the section and tab parse alone', () => {
    const hash = '#settings/log_processor/cplugs?highlight=log_processor.cplugs.example';
    expect(settingsTabOf(hash)).toEqual({ section: 'log_processor', tab: 'cplugs' });
    expect(settingsHighlightOf(hash)).toBe('log_processor.cplugs.example');
    expect(settingsHighlightOf('#settings/log_processor/cplugs')).toBeNull();
    expect(settingsHighlightOf('#settings/nope?highlight=x')).toBeNull();
    expect(settingsHighlightOf('#settings/log_processor?highlight=BAD id')).toBeNull();
});

test('show() with ?highlight= lands on the tab, flashes the control once it renders, and drops the suffix', async () => {
    const target = document.createElement('div');
    document.body.append(target);
    handle = mount(SettingsScreen, { target, props: {} }) as Record<string, unknown>;
    window.location.hash = '#settings/log_processor/cplugs?highlight=log_processor.cplugs.example';
    (handle as unknown as { show(): void }).show();
    flushSync();
    await tick();
    expect(settingsView.section).toBe('log_processor');
    expect(settingsView.tabOf('log_processor')).toBe('cplugs');
    expect(window.location.hash).toBe('#settings/log_processor/cplugs');
    const control = document.createElement('button');
    control.dataset.highlight = 'log_processor.cplugs.example';
    const scrolled = vi.fn();
    control.scrollIntoView = scrolled;
    document.body.append(control);
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(control.classList.contains(HIGHLIGHT_CLASS)).toBe(true);
    expect(scrolled).toHaveBeenCalledWith({ block: 'center' });
});
