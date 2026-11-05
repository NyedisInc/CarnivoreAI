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
    { id: 'huddle', name_key: 'cplug.huddle.name', version: '1.0.0', tier: 'builtin', enabled: true, state: 'active', revision: 1, settings_schema: { version: 1, fields: { a: { kind: 'number', labelKey: 'x', default: 1 } } } },
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

async function pluginsPage(): Promise<HTMLElement> {
    const adapter: ManagerAdapter = { list: async () => ROWS.map((row) => toCplugItem(row, t)), setEnabled: async () => toCplugItem(ROWS[2]!, t) };
    const target = document.createElement('div');
    document.body.append(target);
    mounted = mount(PluginsScreen, { target, props: { embedded: true, scope: 'plugins', adapter, t, loadActivity: async () => [] } });
    await settle();
    return target;
}

const names = (root: HTMLElement): string[] => [...root.querySelectorAll('.catalog-card__title, .mgr-card__name')].map((el) => el.textContent?.trim() ?? '');

describe('the plugins page', () => {
    test('lists the store plugin and no compiled-in item, the dev tier included', async () => {
        expect(names(await pluginsPage())).toEqual(['acme clock']);
    });

    test('a link to an enabled built-in with settings lands on its features entry in the rail', async () => {
        window.location.hash = '#plugins/huddle/settings';
        await pluginsPage();
        expect(window.location.hash).toBe('#settings/plugin/huddle');
    });

    test('a link that names a feature hands over to its pane in Settings > features', async () => {
        window.location.hash = '#plugins/publicboard/settings';
        await pluginsPage();
        expect(window.location.hash).toBe('#settings/features/publicboard');
    });
});

describe('the hand-over to Settings', () => {
    test('replaces the address: back returns to where the owner started, not to the plugins page', async () => {
        window.history.replaceState(null, '', '#start');
        window.history.pushState(null, '', '#plugins/publicboard/settings');
        const before = window.history.length;
        await pluginsPage();
        expect(window.location.hash).toBe('#settings/features/publicboard');
        expect(window.history.length).toBe(before);
        window.history.back();
        await new Promise((resolve) => setTimeout(resolve, 20));
        expect(window.location.hash).toBe('#start');
    });
});
