/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const push = vi.hoisted(() => ({ refresh: null as null | (() => void) }));
vi.mock('../../resource-push/boot', () => ({
    resourcePush: () => ({
        isLive: () => true,
        onChange: () => () => {},
        pushOrPoll: (refresh: () => void, _ms: number, topics: readonly string[]) => {
            if (topics.includes('cplugs')) push.refresh = refresh;
            return () => {};
        },
    }),
}));

import SettingsScreen from '../SettingsScreen.svelte';
import { pluginEntries } from './plugin-entries';
import { pluginSettingsIndex } from './plugin-settings-index.svelte';
import { searchPluginSettings } from '../settings-search';
import { settingsPluginFragment, settingsPluginOf, settingsTabOf } from '../settings-hash';
import { settingsDoc } from '../settings-doc.svelte';
import { setLocale, t as realT } from '../../i18n/index.svelte';
import type { Translate } from '../../sessions/types';
import type { CplugRow } from '../../plugins-page/cplugs-adapter';

setLocale('en');

const WORDS: Record<string, string> = {
    'cplug.flow.name': 'flow runner',
    'cplug.flow.settings.show_tab': 'show the flow tab',
    'cplug.flow.settings.show_tab_help': 'zebra crossing for the tab',
    'cplug.flow.settings.speed': 'run speed',
    'cplug.flow.settings.speed_words': 'tempo pace',
    'cplug.notes.name': 'notes keeper',
    'cplug.notes.settings.wrap': 'wrap long lines',
};
const t: Translate = (key, params) => WORDS[key] ?? realT(key, params);

const FLOW: CplugRow = {
    id: 'flow', name_key: 'cplug.flow.name', enabled: true, state: 'active', revision: 1, settings: { showTab: true, speed: 2 },
    settings_schema: {
        version: 1,
        fields: {
            showTab: { kind: 'boolean', labelKey: 'cplug.flow.settings.show_tab', hintKey: 'cplug.flow.settings.show_tab_help', default: true },
            speed: { kind: 'number', labelKey: 'cplug.flow.settings.speed', keywordsKey: 'cplug.flow.settings.speed_words', min: 1, max: 9, default: 2 },
        },
    },
};
const NOTES: CplugRow = {
    id: 'notes', name_key: 'cplug.notes.name', enabled: true, state: 'active', revision: 1, settings: { wrap: false },
    settings_schema: { version: 1, fields: { wrap: { kind: 'boolean', labelKey: 'cplug.notes.settings.wrap', default: false } } },
};
const BARE: CplugRow = { id: 'bare', name_key: 'cplug.bare.name', enabled: true, state: 'active', revision: 1 };

let listing: CplugRow[] = [];
let handle: Record<string, unknown> | null = null;

async function settle(): Promise<void> {
    for (let i = 0; i < 40; i += 1) await Promise.resolve();
    await tick();
    flushSync();
}

function answer(url: string): Response {
    if (url.endsWith('/cplugs')) return new Response(JSON.stringify({ cplugs: listing }), { status: 200 });
    return new Response(JSON.stringify({ workspace: {}, server_prefs: {}, server: {}, notifications: {} }), { status: 200 });
}

async function mountPage(embedded = true): Promise<HTMLElement> {
    const target = document.createElement('div');
    document.body.append(target);
    handle = mount(SettingsScreen, { target, props: { embedded, t } }) as Record<string, unknown>;
    flushSync();
    (handle as unknown as { show(): void }).show();
    await settle();
    return target;
}

const railIds = (root: HTMLElement): string[] => [...root.querySelectorAll<HTMLElement>('.st-nav button[data-plugin]')].map((el) => el.dataset.plugin!);

beforeEach(() => {
    listing = [FLOW, NOTES, BARE];
    push.refresh = null;
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => answer(String(input))));
    settingsDoc.discard();
    window.location.hash = '';
});

afterEach(() => {
    if (handle) unmount(handle);
    handle = null;
    settingsDoc.discard();
    document.body.innerHTML = '';
    window.location.hash = '';
    vi.unstubAllGlobals();
});

describe('which plugins get an entry', () => {
    test('only plugins that are on and have settings, by display name', () => {
        const off: CplugRow = { ...NOTES, id: 'off', enabled: false, state: 'disabled' };
        const removed: CplugRow = { ...NOTES, id: 'gone', state: 'removed' };
        expect(pluginEntries([NOTES, off, BARE, removed, FLOW], t).map((e) => e.id)).toEqual(['flow', 'notes']);
        expect(pluginEntries([off, BARE], t)).toEqual([]);
    });

    test('the heading lists them, and is hidden when none qualify', async () => {
        const root = await mountPage();
        expect(railIds(root)).toEqual(['flow', 'notes']);
        expect(root.querySelector('[data-st-plugins-heading]')?.textContent).toBe('plugins');
        expect(root.querySelector('.st-nav button[data-plugin="flow"] .st-nav__label')?.textContent).toBe('flow runner');
        unmount(handle!);
        handle = null;
        document.body.innerHTML = '';
        listing = [{ ...NOTES, enabled: false, state: 'disabled' }, BARE];
        const empty = await mountPage();
        expect(railIds(empty)).toEqual([]);
        expect(empty.querySelector('[data-st-plugins-heading]')).toBeNull();
    });

    test('a plugin turned off drops out on a push, and the one being viewed hands back to a section', async () => {
        const root = await mountPage();
        root.querySelector<HTMLButtonElement>('.st-nav button[data-plugin="notes"]')!.click();
        await settle();
        expect(root.querySelector('[data-plugin-entry="notes"]')).not.toBeNull();
        expect(push.refresh).not.toBeNull();
        listing = [FLOW, { ...NOTES, enabled: false, state: 'disabled' }];
        push.refresh!();
        await settle();
        expect(railIds(root)).toEqual(['flow']);
        expect(root.querySelector('[data-plugin-entry]')).toBeNull();
        expect(root.querySelector('.st-section[data-section]')).not.toBeNull();
    });
});

describe('an entry', () => {
    test('opens the same PluginSettings form, with its fields', async () => {
        const root = await mountPage(false);
        root.querySelector<HTMLButtonElement>('.st-nav button[data-plugin="flow"]')!.click();
        await settle();
        const entry = root.querySelector('[data-plugin-entry="flow"]')!;
        expect(entry.querySelector('[data-plugin-settings]')).not.toBeNull();
        expect([...entry.querySelectorAll<HTMLElement>('[data-setting]')].map((el) => el.dataset.setting)).toEqual(['showTab', 'speed']);
        expect(window.location.hash).toBe('#settings/plugin/flow');
    });

    test('its deep link round-trips and opens the entry', async () => {
        expect(settingsPluginOf(settingsPluginFragment('flow'))).toBe('flow');
        expect(settingsPluginOf('settings/plugin/flow?highlight=x')).toBe('flow');
        expect(settingsPluginOf('#settings/appearance')).toBeNull();
        expect(settingsTabOf('#settings/plugin/flow')).toBeNull();
        window.location.hash = settingsPluginFragment('notes');
        const root = await mountPage(false);
        expect(root.querySelector('[data-plugin-entry="notes"]')).not.toBeNull();
        expect(root.querySelector('button[data-plugin="notes"][aria-current="page"]')).not.toBeNull();
        expect(window.location.hash).toBe('#settings/plugin/notes');
    });

    test('a link to a plugin that is off falls back to a section and rewrites the address', async () => {
        window.location.hash = settingsPluginFragment('bare');
        const root = await mountPage(false);
        expect(root.querySelector('[data-plugin-entry]')).toBeNull();
        expect(window.location.hash).toMatch(/^#settings\/[a-z_]+/);
        expect(window.location.hash).not.toContain('plugin/');
    });
});

describe('search', () => {
    const entries = () => pluginEntries([FLOW, NOTES], t);

    test('finds a field by label, by hint, by keywords and by plugin name', () => {
        expect(searchPluginSettings('run speed', t, entries())[0]).toMatchObject({ anchor: 'speed' });
        expect(searchPluginSettings('zebra', t, entries()).map((m) => m.anchor)).toEqual(['showTab']);
        expect(searchPluginSettings('tempo', t, entries()).map((m) => m.anchor)).toEqual(['speed']);
        const byName = searchPluginSettings('notes', t, entries());
        expect(byName.map((m) => [m.entry.id, m.anchor])).toEqual([['notes', null], ['notes', 'wrap']]);
        expect(searchPluginSettings('nothing like it', t, entries())).toEqual([]);
        expect(searchPluginSettings('  ', t, entries())).toEqual([]);
    });

    test('a label hit outranks a hint hit, and a second word narrows', () => {
        const rank = searchPluginSettings('tab', t, entries()).map((m) => m.anchor);
        expect(rank[0]).toBe('showTab');
        expect(searchPluginSettings('tab zebra', t, entries()).map((m) => m.anchor)).toEqual(['showTab']);
    });

    test('a hit shows in the results naming its plugin, and opens that entry at the field', async () => {
        const root = await mountPage();
        const box = root.querySelector<HTMLInputElement>('input[type="search"], input')!;
        box.value = 'zebra';
        box.dispatchEvent(new Event('input', { bubbles: true }));
        await settle();
        const hit = root.querySelector<HTMLButtonElement>('[data-hit-plugin="flow"]')!;
        expect(hit.querySelector('.st-hit__section')?.textContent).toBe('plugins › flow runner');
        expect(hit.dataset.hitAnchor).toBe('showTab');
        expect(root.querySelector('.st-nav button[data-plugin="flow"] .st-nav__count')?.textContent).toBe('1');
        hit.click();
        await settle();
        expect(root.querySelector('[data-plugin-entry="flow"]')).not.toBeNull();
        expect(root.querySelector('[data-hit-plugin]')).toBeNull();
    });
});

describe('the index', () => {
    test('a failed read keeps the rows and says nothing answered', async () => {
        vi.stubGlobal('fetch', vi.fn(async () => { throw new Error('offline'); }));
        pluginSettingsIndex.read = false;
        await pluginSettingsIndex.load();
        expect(pluginSettingsIndex.read).toBe(false);
    });
});
