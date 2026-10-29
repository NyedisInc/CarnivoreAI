/** @vitest-environment jsdom */
import { afterEach, describe, expect, test } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

import PluginsScreen from './PluginsScreen.svelte';
import { toCplugItem, type CplugRow } from './cplugs-adapter';
import type { ManagerAdapter } from '../manager-frame/types';
import { createI18n } from '../../../../client/js/i18n/runtime.js';
import type { Translate } from '../sessions/types';
import { MCPHEALTH_STRINGS } from './mcphealth-strings.fixture';

const en = createI18n({ locale: 'en' }) as { t: Translate; extendCatalog: (id: string, slice: Record<string, string>) => number };
en.extendCatalog('mcphealth', MCPHEALTH_STRINGS);
const t: Translate = (key, params) => en.t(key, params);

const ROWS: CplugRow[] = [
    { id: 'unread', name_key: 'cplug.unread.name', description_key: 'cplug.unread.description', version: '1.0.0', tier: 'builtin', icon: 'bell', author: 'Alex (Example-owner)', surfaces: { plugins: ['session-card-action'] }, enabled: true, state: 'active', permissions: { app: [] } },
    {
        id: 'mcphealth', name_key: 'cplug.mcphealth.name', description_key: 'cplug.mcphealth.description', version: '1.0.0', tier: 'builtin', icon: 'plug', author: 'Joe (ccsliinc)', surfaces: {}, enabled: false, state: 'disabled',
        permissions: { app: ['sessions.read', 'notify'] }, grants: { app: [] }, risks: { 'sessions.read': 'low', notify: 'low' },
        settings_schema: { version: 1, fields: { notify: { kind: 'boolean', labelKey: 'cplug.mcphealth.settings.notify', default: false } } },
    },
    { id: 'huddle', name_key: 'cplug.huddle.name', description_key: 'cplug.huddle.description', version: '1.0.0', tier: 'builtin', icon: 'list', author: 'Joe (ccsliinc)', surfaces: { tabs: ['huddle'], mcp_tools: ['huddle_list'] }, enabled: true, state: 'needs_approval', permissions: { app: ['sessions.message'] }, grants: { app: [] }, risks: { 'sessions.message': 'high' } },
    { id: 'flow', name_key: 'cplug.flow.name', description_key: 'cplug.flow.description', version: '1.0.0', tier: 'builtin', icon: 'plug', author: 'Joe (ccsliinc)', enabled: true, state: 'unavailable', permissions: { app: [] } },
    { id: 'share', name_key: 'cplug.share.name', description_key: 'cplug.share.description', version: '1.0.0', tier: 'core', icon: 'search', enabled: true, state: 'active', permissions: { app: [] } },
    { id: 'gone', enabled: false, state: 'removed' },
];

let mounted: Record<string, unknown> | null = null;

afterEach(() => {
    if (mounted) unmount(mounted);
    mounted = null;
    document.body.innerHTML = '';
    localStorage.clear();
});

async function settle(): Promise<void> {
    for (let i = 0; i < 3; i += 1) await Promise.resolve();
    await tick();
    flushSync();
}

async function show(): Promise<HTMLElement> {
    const adapter: ManagerAdapter = { list: async () => ROWS.map((row) => toCplugItem(row, t)), setEnabled: async (id) => toCplugItem(ROWS.find((r) => `cplug:${r.id}` === id)!, t) };
    const target = document.createElement('div');
    document.body.append(target);
    mounted = mount(PluginsScreen, { target, props: { embedded: true, adapter, t, loadActivity: async () => [] } });
    await settle();
    return target;
}

const MOUNT_IDS = /\b(info-tip|mgr)-[a-z0-9]{6,}\b/g;

/* the reading pane */
function listSide(root: HTMLElement): string {
    const copy = root.cloneNode(true) as HTMLElement;
    copy.querySelectorAll('.oc-page__detail').forEach((pane) => pane.remove());
    return copy.innerHTML.replace(MOUNT_IDS, '$1-id');
}

describe('the plugin list', () => {
    test('the grid, its search, filters, sort and toggle are unchanged', async () => {
        const root = await show();
        await expect(listSide(root)).toMatchFileSnapshot('./__snapshots__/plugin-list.grid.html');
    });

    test('the list view is unchanged', async () => {
        localStorage.setItem('carnivore.view.plugins', 'list');
        const root = await show();
        expect(root.querySelector('.oc-page__items--list'), 'the list view is drawn').not.toBeNull();
        await expect(listSide(root)).toMatchFileSnapshot('./__snapshots__/plugin-list.rows.html');
    });

    test('with a plugin open, the list side is unchanged', async () => {
        const root = await show();
        root.querySelector<HTMLButtonElement>('[data-item-id="cplug:mcphealth"] .catalog-card__open')!.click();
        await settle();
        expect(root.querySelector('.oc-page__detail'), 'the pane is open').not.toBeNull();
        await expect(listSide(root)).toMatchFileSnapshot('./__snapshots__/plugin-list.open.html');
    });
});
