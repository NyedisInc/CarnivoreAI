/** @vitest-environment jsdom */
import { afterEach, describe, expect, test } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

import PluginsScreen from './PluginsScreen.svelte';
import { toCplugItem, type CplugRow } from './cplugs-adapter';
import { createI18n } from '../../../../client/js/i18n/runtime.js';
import type { ManagerAdapter } from '../manager-frame/types';
import type { Translate } from '../sessions/types';

const en = createI18n({ locale: 'en' }) as { t: Translate };
const t: Translate = (key, params) => en.t(key, params);

const ROWS: CplugRow[] = [
    { id: 'publicboard', name_key: 'cplug.publicboard.name', version: '1.0.0', tier: 'builtin', enabled: false, state: 'disabled', revision: 1 },
    { id: 'tmdevtools', name_key: 'cplug.tmdevtools.name', version: '1.0.0', tier: 'dev', enabled: false, state: 'disabled', revision: 1 },
    { id: 'taskmanager', name_key: 'cplug.huddle.name', version: '1.0.0', tier: 'builtin', enabled: true, state: 'active', revision: 1, settings_schema: { version: 1, fields: { a: { kind: 'number', labelKey: 'x', default: 1 } } } },
    { id: 'acme', name: 'acme clock', version: '1.0.0', tier: 'catalog', runtime: 'sidecar', publisher: 'acme', enabled: true, state: 'active', revision: 1 },
];

let mounted: Record<string, unknown> | null = null;
afterEach(() => {
    if (mounted) unmount(mounted);
    mounted = null;
    document.body.innerHTML = '';
    window.location.hash = '';
});

async function settle(): Promise<void> {
    for (let i = 0; i < 4; i += 1) await Promise.resolve();
    await tick();
    flushSync();
}

async function pluginsPage(developerMode = false): Promise<HTMLElement> {
    const adapter: ManagerAdapter = { list: async () => ROWS.map((row) => toCplugItem(row, t)), setEnabled: async () => toCplugItem(ROWS[2]!, t) };
    const target = document.createElement('div');
    document.body.append(target);
    mounted = mount(PluginsScreen, { target, props: { embedded: true, scope: 'plugins', developerMode, adapter, t, loadActivity: async () => [] } });
    await settle();
    return target;
}

const names = (root: HTMLElement): string[] => [...root.querySelectorAll('.catalog-card__title, .mgr-card__name')].map((el) => el.textContent?.trim() ?? '');

describe('the plugins page', () => {
    test('unifies built-in and store plugins while gating dev tier behind developerMode', async () => {
        expect(names(await pluginsPage())).toEqual(['acme clock', 'cplug.publicboard.name', 'task manager']);
    });

    test('lists the dev tier too when developerMode is enabled', async () => {
        expect(names(await pluginsPage(true))).toEqual(['acme clock', 'cplug.publicboard.name', 'task manager', 'task-manager-dev-tools']);
    });

    test('a link to an enabled built-in with settings opens its settings inline inside Plugins', async () => {
        window.location.hash = '#plugins/taskmanager/settings';
        const root = await pluginsPage();
        expect(window.location.hash).toBe('#plugins/taskmanager/settings');
        expect(root.querySelector('[data-plugin-pane="taskmanager"]')).not.toBeNull();
        expect(root.querySelector('[data-plugin-panel="settings"]')).not.toBeNull();
    });

    test('an old link that names the renamed id opens the same settings inline (#3260)', async () => {
        window.location.hash = '#plugins/huddle/settings';
        const root = await pluginsPage();
        expect(root.querySelector('[data-plugin-pane="taskmanager"]')).not.toBeNull();
        expect(root.querySelector('[data-plugin-panel="settings"]')).not.toBeNull();
    });

    test('a link that names a feature opens directly in Plugins without redirecting to Settings > features', async () => {
        window.location.hash = '#plugins/publicboard/settings';
        const root = await pluginsPage();
        expect(window.location.hash).toBe('#plugins/publicboard/settings');
        expect(root.querySelector('[data-plugin-pane="publicboard"]')).not.toBeNull();
    });
});

describe('legacy feature link stays on the plugins page', () => {
    test('does not rewrite the hash to Settings > features on mount', async () => {
        window.history.replaceState(null, '', '#start');
        window.history.pushState(null, '', '#plugins/publicboard/settings');
        const before = window.history.length;
        const root = await pluginsPage();
        expect(window.location.hash).toBe('#plugins/publicboard/settings');
        expect(window.history.length).toBe(before);
        expect(root.querySelector('[data-plugin-pane="publicboard"]')).not.toBeNull();
    });
});
