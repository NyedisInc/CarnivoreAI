/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';
import PluginsScreen from './PluginsScreen.svelte';
import { toCplugItem, type CplugRow } from './cplugs-adapter';
import { EXTRA_SETTINGS_PLUGINS, hasPluginSettings, pluginLinkOf, pluginSettingsHash } from './plugin-settings-link';
import { PLUGIN_SETTINGS_EXTRAS } from './plugin-extras';
import '../plugins/builtin';
import { cplugEnablement } from '../../cplugs/host/enablement.svelte';
import type { ManagerAdapter } from '../manager-frame/types';

const t = (key: string): string => key;
const FIELDS = { showTab: { kind: 'boolean' as const, labelKey: 'cplug.flow.settings.show_tab', default: false } };
const rows: CplugRow[] = [
    { id: 'flow', enabled: true, state: 'active', revision: 1, settings: { showTab: false }, settings_schema: { version: 1, fields: FIELDS } },
    { id: 'unread', enabled: true, state: 'active', revision: 1, settings: {}, settings_schema: { version: 1, fields: {} } },
    { id: 'huddle', enabled: true, state: 'active', revision: 1, settings: { showTab: true }, settings_schema: { version: 1, fields: FIELDS } },
];
const adapter = { list: async () => rows.map((row) => toCplugItem(row, t)) } as unknown as ManagerAdapter;

let screen: Record<string, unknown> | null = null;
afterEach(() => {
    if (screen) unmount(screen);
    screen = null;
    document.body.innerHTML = '';
    window.history.replaceState(null, '', '/');
});

async function draw(hash = ''): Promise<void> {
    window.history.replaceState(null, '', `/${hash}`);
    screen = mount(PluginsScreen, { target: document.body, props: { adapter, t, embedded: true, loadActivity: async () => [] } });
    for (let i = 0; i < 6; i += 1) await tick();
    flushSync();
    await new Promise((resolve) => setTimeout(resolve, 5));
}

describe('the settings rule', () => {
    test('a plugin with fields has settings; one with none, or a removed folder, has not', () => {
        expect(hasPluginSettings(toCplugItem(rows[0]!, t))).toBe(true);
        expect(hasPluginSettings(toCplugItem(rows[1]!, t))).toBe(false);
        expect(hasPluginSettings(toCplugItem({ ...rows[0]!, state: 'removed' }, t))).toBe(false);
    });

    test('the deep link round trips, and the older swarm fragments mean huddle settings', () => {
        expect(pluginSettingsHash('flow')).toBe('#plugins/flow/settings');
        expect(pluginLinkOf('#plugins/flow/settings')).toEqual({ cplugId: 'flow', settings: true });
        expect(pluginLinkOf('#plugins/flow')).toEqual({ cplugId: 'flow', settings: false });
        expect(pluginLinkOf('#swarm-settings')).toEqual({ cplugId: 'huddle', settings: true });
        expect(pluginLinkOf('#interactive-todo')).toEqual({ cplugId: 'huddle', settings: true });
        expect(pluginLinkOf('#plugins')).toBeNull();
        expect(pluginLinkOf('#settings/plugins')).toBeNull();
    });
});

describe('the plugin card gear', () => {
    test('only a plugin with settings carries the gear', async () => {
        await draw();
        expect(document.querySelector('[data-plugin-settings-open="flow"]')).not.toBeNull();
        expect(document.querySelector('[data-plugin-settings-open="huddle"]')).not.toBeNull();
        expect(document.querySelector('[data-plugin-settings-open="unread"]')).toBeNull();
        expect(document.querySelector('[data-item-id="cplug:unread"]')).not.toBeNull();
    });

    test('pressing it opens that plugin\'s side pane on its settings tab', async () => {
        await draw();
        expect(document.querySelector('[data-plugin-settings]')).toBeNull();
        document.querySelector<HTMLElement>('[data-plugin-settings-open="flow"]')!.click();
        for (let i = 0; i < 4; i += 1) await tick();
        flushSync();
        expect(document.querySelector('[role="tab"][aria-selected="true"]')?.getAttribute('data-tab')).toBe('settings');
        expect(document.querySelector('[data-plugin-settings]')?.id).toBe('plugin-settings-flow');
    });
});

describe('the gear under Warez > INSTALLED', () => {
    test('pressing it reports the open plugin and its settings tab to the host, as a name click does', async () => {
        const onSelect = vi.fn();
        screen = mount(PluginsScreen, { target: document.body, props: { adapter, t, embedded: true, onSelect, loadActivity: async () => [] } });
        for (let i = 0; i < 6; i += 1) await tick();
        flushSync();
        onSelect.mockClear();
        document.querySelector<HTMLElement>('[data-plugin-settings-open="flow"]')!.click();
        for (let i = 0; i < 4; i += 1) await tick();
        flushSync();
        expect(onSelect).toHaveBeenLastCalledWith('flow', 'settings');
    });
});

describe('the deep link', () => {
    test('#plugins/flow/settings opens the page with flow\'s pane on its settings tab', async () => {
        await draw('#plugins/flow/settings');
        expect(document.querySelector('[role="tab"][aria-selected="true"]')?.getAttribute('data-tab')).toBe('settings');
        expect(document.querySelector('[data-plugin-settings]')?.id).toBe('plugin-settings-flow');
    });

    test('#swarm-settings opens huddle\'s pane, with the swarm block inside the same section', async () => {
        await draw('#swarm-settings');
        const section = document.querySelector('#plugin-settings-huddle');
        expect(section).not.toBeNull();
        expect(section?.querySelector('[data-huddle-swarm-settings]')).not.toBeNull();
        expect(document.querySelector('#plugin-settings-flow')).toBeNull();
    });

    test('a plain #plugins opens no pane', async () => {
        await draw('#plugins');
        expect(document.querySelector('[data-plugin-settings]')).toBeNull();
    });
});

describe('the panels that moved out of Settings', () => {
    const bare = (id: string): CplugRow => ({ id, enabled: true, state: 'active', revision: 1, settings: {}, settings_schema: { version: 1, fields: {} } });

    test('the gear rule and the extras map name the same plugins', () => {
        expect([...EXTRA_SETTINGS_PLUGINS].sort()).toEqual([...Object.keys(PLUGIN_SETTINGS_EXTRAS), 'crate', 'save'].sort());
        for (const id of ['save']) expect(hasPluginSettings(toCplugItem(bare(id), t)), id).toBe(true);
        expect(hasPluginSettings(toCplugItem(bare('unread'), t))).toBe(false);
    });

    test('conversation backups draw their panel inside the settings section', async () => {
        vi.stubGlobal('fetch', vi.fn(async () => new Response('{}', { status: 500 })));
        cplugEnablement.enabled = { save: true };
        try {
            const blocks: Array<[string, string]> = [['save', 'data-save-settings']];
            for (const [id, marker] of blocks) {
                rows.splice(0, rows.length, bare(id));
                await draw(`#plugins/${id}/settings`);
                expect(document.querySelector(`#plugin-settings-${id} [${marker}]`), id).not.toBeNull();
                expect(document.querySelector(`[data-plugin-settings-open="${id}"]`), id).not.toBeNull();
                unmount(screen!);
                screen = null;
                document.body.innerHTML = '';
            }
        } finally {
            cplugEnablement.enabled = {};
            vi.unstubAllGlobals();
        }
    });

    test('conversation backups draw no block while the plugin is off', async () => {
        vi.stubGlobal('fetch', vi.fn(async () => new Response('{}', { status: 500 })));
        cplugEnablement.enabled = { save: false };
        try {
            rows.splice(0, rows.length, bare('save'));
            await draw('#plugins/save/settings');
            expect(document.querySelector('[data-save-settings]')).toBeNull();
        } finally {
            cplugEnablement.enabled = {};
            vi.unstubAllGlobals();
        }
    });
});
