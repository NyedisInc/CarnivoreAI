/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';
import PluginSettings from './PluginSettings.svelte';
import { setCplugSetting, toCplugItem, type CplugRow } from './cplugs-adapter';
import { formIsShown } from './plugin-extras';

const t = (key: string): string => key;
const ROW: CplugRow = {
    id: 'flow', enabled: true, state: 'active', revision: 3,
    settings: { showTab: false },
    settings_schema: { version: 1, fields: { showTab: { kind: 'boolean', labelKey: 'cplug.flow.settings.show_tab', default: false } } },
};
let mounted: Record<string, unknown> | null = null;
afterEach(() => { if (mounted) unmount(mounted); mounted = null; document.body.innerHTML = ''; });

async function draw(write: (id: string, key: string, value: boolean | number | string) => Promise<ReturnType<typeof toCplugItem>>) {
    const target = document.createElement('div');
    document.body.append(target);
    mounted = mount(PluginSettings, { target, props: { plugin: toCplugItem(ROW, t), t, write } });
    await tick();
    flushSync();
    return target;
}

describe('PluginSettings', () => {
    test('a boolean toggle writes the key and value once, and the row it answers is shown', async () => {
        const write = vi.fn(async () => toCplugItem({ ...ROW, settings: { showTab: true } }, t));
        const root = await draw(write);
        expect(root.textContent).toContain('cplug.flow.settings.show_tab');
        root.querySelector<HTMLElement>('[data-setting="showTab"] [role="switch"]')!.click();
        await tick();
        flushSync();
        expect(write).toHaveBeenCalledExactlyOnceWith('flow', 'showTab', true);
        expect(root.querySelector('[data-setting="showTab"] [data-on="1"]')).not.toBeNull();
    });

    test('a refused write shows the error under the field and keeps the stored value', async () => {
        const root = await draw(async () => { throw new Error('nope'); });
        root.querySelector<HTMLElement>('[data-setting="showTab"] [role="switch"]')!.click();
        await tick();
        flushSync();
        expect(root.querySelector('[role="alert"]')?.textContent).toBe('plugins.page.settings.failed');
        expect(root.querySelector('[data-setting="showTab"] [data-on="0"]')).not.toBeNull();
    });

    test('advice the save answered with keeps its detail and shows under the field it names, apart from the permission warnings', async () => {
        const advised: CplugRow = {
            ...ROW,
            settings: { showTab: true },
            warnings: [{ code: 'sends_transcripts', reads: 'feed.view: raw', host: 'api.github.com' }],
            settings_warnings: [
                { code: 'same_disk_transcripts', message: 'same disk as your transcripts', field: 'showTab', detail: '/v is on the same disk as /t, so these copies are lost together' },
                { code: 'other', message: 'about another field', field: 'elsewhere', detail: 'not here' },
            ],
        };
        const item = toCplugItem(advised, t);
        expect(item.settingsWarnings).toHaveLength(2);
        expect(item.warnings).toEqual(['plugins.page.warning.sends_transcripts']);
        const root = await draw(async () => item);
        root.querySelector<HTMLElement>('[data-setting="showTab"] [role="switch"]')!.click();
        await tick();
        flushSync();
        const shown = root.querySelectorAll('[data-setting="showTab"] [data-setting-warning]');
        expect(shown).toHaveLength(1);
        expect(shown[0]!.querySelector('.sf__warn-message')?.textContent).toBe('same disk as your transcripts');
        expect(shown[0]!.querySelector('.sf__warn-detail')?.textContent).toContain('lost together');
        expect(root.textContent).not.toContain('about another field');
    });

    test('the form is skipped only when the plugin panel draws every field', () => {
        const none = { version: 1, fields: {} } as const;
        const one = { version: 1, fields: { showTab: { kind: 'boolean', labelKey: 'k', default: false } } } as never;
        expect(formIsShown(none, true)).toBe(false);
        expect(formIsShown(none, false)).toBe(true);
        expect(formIsShown(one, true)).toBe(true);
        expect(formIsShown(null, true)).toBe(false);
    });

    test('no fields means no section, and the route is PUT /cplugs/{id} with the revision and one setting', async () => {
        expect(toCplugItem({ ...ROW, settings_schema: { version: 1, fields: {} } }, t).settingsSchema).toBeNull();
        const calls: Array<[string, string?]> = [];
        const fetcher = (async (path: string, init?: { method?: string; body?: string }) => {
            calls.push([init?.method ?? 'GET', init?.body]);
            return ROW;
        }) as never;
        await setCplugSetting('flow', 'showTab', true, t, fetcher, async () => {});
        expect(calls).toEqual([['GET', undefined], ['PUT', JSON.stringify({ revision: 3, settings: { showTab: true } })]]);
    });
});
