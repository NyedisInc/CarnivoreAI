/** @vitest-environment jsdom */
import { afterEach, describe, expect, test } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

import PluginsScreen from './PluginsScreen.svelte';
import { featureRows, featureWords } from './feature-words';
import { toCplugItem, type CplugRow } from './cplugs-adapter';
import { CATALOGS } from '../../../../client/js/i18n/catalogs.js';
import { createI18n } from '../../../../client/js/i18n/runtime.js';
import type { ManagerAdapter } from '../manager-frame/types';
import type { Translate } from '../sessions/types';

const messages = CATALOGS.en!.messages as Record<string, unknown>;
const en = createI18n({ locale: 'en' }) as { t: Translate };
const t: Translate = (key, params) => en.t(key, params);
const FORBIDDEN = /\bplugins?\b|\bbuilt[- ]in\b/i;

describe('the feature twin keys', () => {
    const twins = Object.keys(messages).filter((key) => key.startsWith('features.page.'));

    test('there are twins, and each replaces a plugins.page sentence that exists', () => {
        expect(twins.length).toBeGreaterThan(10);
        for (const key of twins) expect(messages, key).toHaveProperty(`plugins.page.${key.slice('features.page.'.length)}`);
    });

    test('every plugins.page sentence that says "plugin" has a twin, unless only a store or sideloaded item can show it', () => {
        const STORE_ONLY = /^plugins\.page\.(limit\.catalog|catalog\.|third_party\.|sideload\.)/;
        const missing = Object.keys(messages).filter(
            (key) => key.startsWith('plugins.page.') && /\bplugins?\b/i.test(JSON.stringify(messages[key])) && !STORE_ONLY.test(key) && !twins.includes(`features.page.${key.slice('plugins.page.'.length)}`),
        );
        expect(missing).toEqual([]);
    });

    test('no twin says "plugin" or "built in"', () => {
        for (const key of twins) expect(JSON.stringify(messages[key]), key).not.toMatch(FORBIDDEN);
    });
});

describe('featureWords', () => {
    const words = featureWords(t);

    test('a key with a twin reads the twin, with its parameters', () => {
        expect(words('plugins.page.pane.kicker')).toBe('feature');
        expect(words('plugins.page.deps.needed_by_nobody', { name: 'review board' })).toBe('no feature needs review board');
    });

    test('a key with no twin, and a key outside plugins.page, read as they are', () => {
        expect(words('plugins.page.pane.tab.overview')).toBe(t('plugins.page.pane.tab.overview'));
        expect(words('settings.plugins.heading')).toBe('plugins');
    });
});

describe('featureRows', () => {
    const rows = [{ id: 'a', tier: 'builtin' }, { id: 'b', tier: 'core' }, { id: 'c', tier: 'dev' }, { id: 'd', tier: 'catalog' }, { id: 'e', tier: 'local' }, { id: 'f', tier: '' }];

    test('compiled-in rows only: the dev tier needs developer mode, a store or sideloaded row never', () => {
        expect(featureRows(rows, false).map((r) => r.id)).toEqual(['a', 'b']);
        expect(featureRows(rows, true).map((r) => r.id)).toEqual(['a', 'b', 'c']);
    });
});

const REVIEWBOARD: CplugRow = {
    id: 'reviewboard', name_key: 'cplug.reviewboard.name', description_key: 'cplug.reviewboard.description', version: '1.0.0', tier: 'builtin',
    enabled: true, state: 'active', revision: 1, permissions: { app: [] },
    dependencies: { needed_by: [{ id: 'publicboard', enabled: true }], enabled_dependents: ['publicboard'] },
};
const PUBLICBOARD: CplugRow = {
    id: 'publicboard', name_key: 'cplug.publicboard.name', description_key: 'cplug.publicboard.description', version: '1.0.0', tier: 'builtin',
    enabled: false, state: 'disabled', revision: 1, permissions: { app: ['sessions.read'] }, risks: { 'sessions.read': 'low' },
    dependencies: { plugins: [{ id: 'reviewboard', status: 'off' }] },
};

let mounted: Record<string, unknown> | null = null;
afterEach(() => {
    if (mounted) unmount(mounted);
    mounted = null;
    document.body.innerHTML = '';
});

async function settle(): Promise<void> {
    for (let i = 0; i < 4; i += 1) await Promise.resolve();
    await tick();
    flushSync();
}

async function featuresPage(focusId: string, focusTab: string): Promise<HTMLElement> {
    const tf = featureWords(t);
    const adapter: ManagerAdapter = { list: async () => [REVIEWBOARD, PUBLICBOARD].map((row) => toCplugItem(row, tf)), setEnabled: async () => toCplugItem(REVIEWBOARD, tf) };
    const target = document.createElement('div');
    document.body.append(target);
    mounted = mount(PluginsScreen, { target, props: { embedded: true, scope: 'features', adapter, t, focusId, focusTab, loadActivity: async () => [] } });
    await settle();
    return target;
}

describe('a features page', () => {
    test('says "feature" and never "plugin" or "built in": the list, the overview, the permissions, the dependencies', async () => {
        for (const [id, tab] of [['publicboard', 'overview'], ['publicboard', 'permissions'], ['reviewboard', 'overview'], ['reviewboard', 'data']] as const) {
            const root = await featuresPage(id, tab);
            const text = root.textContent ?? '';
            expect(text, `${id}/${tab}`).not.toMatch(FORBIDDEN);
            expect(text, `${id}/${tab}`).toMatch(/\bfeatures?\b/);
            unmount(mounted!);
            mounted = null;
            document.body.innerHTML = '';
        }
    });

    test('turning off an item that others need asks first, in feature words', async () => {
        const root = await featuresPage('reviewboard', 'overview');
        root.querySelector<HTMLButtonElement>('[data-plugin-pane-switch="reviewboard"]')!.click();
        await settle();
        const ask = root.querySelector('[data-cplug-disable-ask]');
        expect(ask).not.toBeNull();
        expect(ask!.textContent).not.toMatch(FORBIDDEN);
        expect(ask!.textContent).toMatch(/\bfeature\b/);
    });
});
