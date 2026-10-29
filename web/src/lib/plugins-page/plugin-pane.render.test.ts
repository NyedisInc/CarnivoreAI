/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

import PluginsScreen from './PluginsScreen.svelte';
import { toCplugItem, type CplugRow, type CplugSheet } from './cplugs-adapter';
import { bytesText, paneReason, paneTabs, purgeBlocked, surfaceChips, type PurgePrice } from './plugin-pane';
import type { ManagerAdapter } from '../manager-frame/types';
import { createI18n } from '../../../../client/js/i18n/runtime.js';
import type { Translate } from '../sessions/types';
import { MCPHEALTH_STRINGS } from './mcphealth-strings.fixture';

const en = createI18n({ locale: 'en' }) as { t: Translate; extendCatalog: (id: string, slice: Record<string, string>) => number };
en.extendCatalog('mcphealth', MCPHEALTH_STRINGS);
const t: Translate = (key, params) => en.t(key, params);

const MCP: CplugRow = {
    id: 'mcphealth', name_key: 'cplug.mcphealth.name', description_key: 'cplug.mcphealth.description', version: '1.0.0', tier: 'builtin',
    author: 'Joe (ccsliinc)', surfaces: {}, enabled: false, state: 'disabled', storage_bytes: 12_700,
    permissions: { app: ['sessions.read', 'notify'] }, grants: { app: [] }, needs: ['sessions.read', 'notify'], risks: { 'sessions.read': 'low', notify: 'low' },
    settings: { warnMode: 'all', servers: '', notify: false },
    settings_schema: {
        version: 1,
        fields: {
            warnMode: { kind: 'enum', labelKey: 'cplug.mcphealth.settings.warn_mode', options: ['all', 'allow', 'block'], default: 'all' },
            servers: { kind: 'string', labelKey: 'cplug.mcphealth.settings.servers', maxLength: 1000, default: '' },
            notify: { kind: 'boolean', labelKey: 'cplug.mcphealth.settings.notify', default: false },
        },
    },
};
const SWARM: CplugRow = {
    id: 'huddle', name_key: 'cplug.huddle.name', version: '1.0.0', tier: 'builtin', enabled: true, state: 'active', storage_bytes: 2_500_000,
    surfaces: { tabs: ['huddle'], mcp_tools: ['a', 'b', 'c'], topics: ['x'] },
    permissions: { app: ['sessions.read', 'sessions.message'] }, grants: { app: ['sessions.read', 'sessions.message'] }, needs: [],
    risks: { 'sessions.read': 'low', 'sessions.message': 'high' },
};

let mounted: Record<string, unknown> | null = null;

afterEach(() => {
    if (mounted) unmount(mounted);
    mounted = null;
    document.body.innerHTML = '';
    localStorage.clear();
});

async function settle(): Promise<void> {
    for (let i = 0; i < 4; i += 1) {
        await tick();
        await Promise.resolve();
    }
    flushSync();
}

async function openPane(rows: CplugRow[], openId: string, extra: Record<string, unknown> = {}): Promise<HTMLElement> {
    const adapter: ManagerAdapter = {
        list: async () => rows.map((row) => toCplugItem(row, t)),
        setEnabled: async (id) => toCplugItem(rows.find((r) => `cplug:${r.id}` === id)!, t),
    };
    const target = document.createElement('div');
    document.body.append(target);
    mounted = mount(PluginsScreen, { target, props: { embedded: true, adapter, t, loadActivity: async () => [], ...extra } });
    await settle();
    target.querySelector<HTMLButtonElement>(`[data-item-id="cplug:${openId}"] .catalog-card__open`)!.click();
    await settle();
    return target;
}

const tabs = (root: HTMLElement): HTMLButtonElement[] => Array.from(root.querySelectorAll<HTMLButtonElement>('.oc-page__detail [role="tab"]'));
const selected = (root: HTMLElement): string | null | undefined => root.querySelector('.oc-page__detail [role="tab"][aria-selected="true"]')?.getAttribute('data-tab');

describe('the tabs', () => {
    test('four tabs in a tablist, one in the tab order, and each opens its own panel', async () => {
        const root = await openPane([MCP], 'mcphealth');
        expect(root.querySelector('.oc-page__detail [role="tablist"]')).not.toBeNull();
        expect(tabs(root).map((tab) => tab.dataset.tab)).toEqual(['overview', 'settings', 'permissions', 'data']);
        expect(tabs(root).map((tab) => tab.tabIndex)).toEqual([0, -1, -1, -1]);
        for (const id of ['settings', 'permissions', 'data', 'overview']) {
            tabs(root).find((tab) => tab.dataset.tab === id)!.click();
            await settle();
            expect(selected(root)).toBe(id);
            const panel = root.querySelector<HTMLElement>('.oc-page__detail [role="tabpanel"]')!;
            expect(panel.dataset.pluginPanel).toBe(id);
            expect(panel.getAttribute('aria-labelledby')).toBe(tabs(root).find((tab) => tab.dataset.tab === id)!.id);
        }
    });

    test('arrows move and wrap, Home and End jump, and the focus follows', async () => {
        const root = await openPane([MCP], 'mcphealth');
        const key = async (name: string) => {
            tabs(root).find((tab) => tab.getAttribute('aria-selected') === 'true')!.dispatchEvent(new KeyboardEvent('keydown', { key: name, bubbles: true }));
            await settle();
        };
        await key('ArrowRight');
        expect(selected(root)).toBe('settings');
        await key('End');
        expect(selected(root)).toBe('data');
        await key('ArrowRight');
        expect(selected(root)).toBe('overview');
        await key('ArrowLeft');
        expect(selected(root)).toBe('data');
        await key('Home');
        expect(selected(root)).toBe('overview');
        await new Promise((resolve) => setTimeout(resolve, 0));
        expect(document.activeElement).toBe(tabs(root)[0]);
        expect(tabs(root).map((tab) => tab.tabIndex)).toEqual([0, -1, -1, -1]);
    });

    test('the chosen tab follows the owner to the next plugin and is remembered on this device', async () => {
        const root = await openPane([MCP, SWARM], 'mcphealth');
        tabs(root).find((tab) => tab.dataset.tab === 'data')!.click();
        await settle();
        root.querySelector<HTMLButtonElement>('[data-item-id="cplug:huddle"] .catalog-card__open')!.click();
        await settle();
        expect(selected(root)).toBe('data');
        expect(localStorage.getItem('carnivore.tabs.plugins-pane')).toBe('data');
        unmount(mounted!);
        mounted = null;
        document.body.innerHTML = '';
        const again = await openPane([MCP], 'mcphealth');
        expect(selected(again)).toBe('data');
    });

    test('the badges are real figures only: field count, ask count, the stored size', async () => {
        const root = await openPane([MCP], 'mcphealth');
        const badge = (id: string) => tabs(root).find((tab) => tab.dataset.tab === id)!.querySelector('.oc-ptab__badge')?.textContent ?? null;
        expect([badge('overview'), badge('settings'), badge('permissions'), badge('data')]).toEqual([null, '3', '2', '12.4 kb']);
    });
});

describe('the reason strip', () => {
    test('it is not drawn for a plugin that is on, off or doing nothing', async () => {
        for (const state of ['active', 'disabled', 'inert']) {
            const root = await openPane([{ ...SWARM, state, enabled: state !== 'disabled' }], 'huddle');
            expect(root.querySelector('[data-plugin-reason]'), state).toBeNull();
            unmount(mounted!);
            mounted = null;
            document.body.innerHTML = '';
        }
    });

    test('a held plugin says so with the host\'s own reason, and has no review button', async () => {
        const root = await openPane([{ ...SWARM, state: 'unavailable', detail: 'start hook failed: OSError' }], 'huddle');
        const strip = root.querySelector<HTMLElement>('[data-plugin-reason="held"]')!;
        expect(strip.textContent).toContain('held: it could not start.');
        expect(strip.textContent).toContain('the host said: start hook failed: OSError');
        expect(strip.querySelector('[data-plugin-review]')).toBeNull();
        expect(root.querySelector('.mgr__detail-bar [data-plugin-state]')?.textContent).toBe('held');
    });

    test('a plugin waiting with nothing to grant says its code changed and points at approve (#2541)', async () => {
        const waiting: CplugRow = { ...SWARM, state: 'needs_approval', permissions: { app: [] }, grants: { app: [] }, needs: [] };
        const root = await openPane([waiting], 'huddle');
        const strip = root.querySelector<HTMLElement>('[data-plugin-reason="grant"]')!;
        expect(strip.textContent).toContain('on, waiting for approval.');
        expect(strip.textContent).toContain('its code changed since you approved it');
        expect(strip.textContent).not.toContain('it asks for');
    });

    test('a plugin waiting for a grant names what is not granted, and review opens the permissions tab', async () => {
        const waiting: CplugRow = { ...SWARM, state: 'needs_approval', grants: { app: ['sessions.read'] }, needs: ['sessions.message'] };
        const root = await openPane([waiting], 'huddle');
        const strip = root.querySelector<HTMLElement>('[data-plugin-reason="grant"]')!;
        expect(strip.textContent).toContain('it asks for send a line to a session, not granted yet');
        expect(selected(root)).toBe('overview');
        strip.querySelector<HTMLButtonElement>('[data-plugin-review]')!.click();
        await settle();
        expect(selected(root)).toBe('permissions');
        expect(tabs(root)[2]!.querySelector('.oc-ptab__dot')).not.toBeNull();
        expect(root.querySelector('[data-perm-row="sessions.message"]')?.classList.contains('plp-row--missing')).toBe(true);
        expect(root.querySelector('[data-perm-row="sessions.read"] [data-perm-granted="true"]')).not.toBeNull();
    });
});

describe('the settings tab', () => {
    test('the form is generated from the plugin\'s settings schema', async () => {
        const root = await openPane([MCP], 'mcphealth');
        tabs(root).find((tab) => tab.dataset.tab === 'settings')!.click();
        await settle();
        const form = root.querySelector('#plugin-settings-mcphealth [data-settings-form]')!;
        expect(form, 'the form is drawn').not.toBeNull();
        expect(Array.from(form.querySelectorAll<HTMLElement>('[data-setting]')).map((el) => el.dataset.setting)).toEqual(['warnMode', 'servers', 'notify']);
        expect(form.textContent).toContain('which servers may raise the !');
        expect(form.querySelector('[data-setting="notify"] [role="switch"]')).not.toBeNull();
    });

    test('a plugin with nothing to set says so instead of an empty tab', async () => {
        const bare = await openPane([{ ...SWARM, id: 'unread', name_key: 'cplug.unread.name' }], 'unread');
        tabs(bare).find((tab) => tab.dataset.tab === 'settings')!.click();
        await settle();
        expect(bare.querySelector('[data-plugin-settings-none]')?.textContent).toBe('mark unread has nothing to set.');
        expect(bare.querySelector('[data-settings-form]')).toBeNull();
    });
});

describe('the data tab', () => {
    const price: PurgePrice = { id: 'mcphealth', files: 3, bytes: 12_700, confirm_token: 'tok123', dry_run: true };

    test('purge is blocked with a plain reason while the plugin is on, and nothing is called', async () => {
        const purge = vi.fn(async () => price);
        const root = await openPane([SWARM], 'huddle', { purge });
        tabs(root).find((tab) => tab.dataset.tab === 'data')!.click();
        await settle();
        const button = root.querySelector<HTMLButtonElement>('[data-purge-price]')!;
        expect(button.disabled).toBe(true);
        expect(root.querySelector('[data-purge-blocked]')?.textContent).toBe('turn task manager off first: purge only runs on a plugin that is off.');
        button.click();
        await settle();
        expect(purge).not.toHaveBeenCalled();
    });

    test('a plugin that is off prices first, deletes only on the coral confirm, then reads the list again', async () => {
        const purge = vi.fn(async (_id: string, token?: string) => (token ? { ...price, dry_run: false } : price));
        const root = await openPane([MCP], 'mcphealth', { purge });
        tabs(root).find((tab) => tab.dataset.tab === 'data')!.click();
        await settle();
        expect(root.querySelector('[data-plugin-size]')?.textContent).toBe('12.4 kb');
        expect(root.querySelector('[data-plugin-folder]')?.textContent).toBe("mcphealth, in carnivore's plugin data folder");
        root.querySelector<HTMLButtonElement>('[data-purge-price]')!.click();
        await settle();
        expect(purge.mock.calls).toEqual([['mcphealth', undefined]]);
        const box = root.querySelector<HTMLElement>('[data-purge-confirm]')!;
        expect(box.textContent).toContain('this deletes 3 files, 12.4 kb, from the folder of mcp health');
        const go = box.querySelector<HTMLButtonElement>('[data-purge-go]')!;
        expect(go.getAttribute('data-btn') === 'danger').toBe(true);
        expect(go.textContent?.trim()).toBe('delete 3 files');
        box.querySelector<HTMLButtonElement>('[data-purge-cancel]')!.click();
        await settle();
        expect(root.querySelector('[data-purge-confirm]')).toBeNull();
        expect(purge).toHaveBeenCalledTimes(1);
        root.querySelector<HTMLButtonElement>('[data-purge-price]')!.click();
        await settle();
        root.querySelector<HTMLButtonElement>('[data-purge-go]')!.click();
        await settle();
        expect(purge.mock.calls[2]).toEqual(['mcphealth', 'tok123']);
        expect(root.querySelector('[data-purge-done]')?.textContent).toBe('purged: 3 files, 12.4 kb, deleted.');
    });

    test('the copy names everything a purge removes: folder, settings, grants and secrets, and that a default-on plugin comes back on', async () => {
        const purge = vi.fn(async () => price);
        const root = await openPane([MCP], 'mcphealth', { purge });
        tabs(root).find((tab) => tab.dataset.tab === 'data')!.click();
        await settle();
        const what = root.querySelector('[data-plugin-purge] .plp-brief')?.textContent ?? '';
        for (const part of ['folder of mcp health', 'settings and grants', 'secrets', 'comes back on', 'cannot be undone']) expect(what).toContain(part);
        root.querySelector<HTMLButtonElement>('[data-purge-price]')!.click();
        await settle();
        const box = root.querySelector('[data-purge-confirm]')?.textContent ?? '';
        for (const part of ['settings, grants and stored secrets', 'comes back on']) expect(box).toContain(part);
    });

    test('a price that is up when the plugin is switched on is dropped, and the token is never sent', async () => {
        const purge = vi.fn(async (_id: string, token?: string) => (token ? { ...price, dry_run: false } : price));
        const on: CplugRow = { ...MCP, enabled: true, state: 'active', grants: { app: ['sessions.read', 'notify'] }, needs: [] };
        const adapter: ManagerAdapter = { list: async () => [toCplugItem(MCP, t)], setEnabled: async () => toCplugItem(on, t) };
        const root = await openPane([MCP], 'mcphealth', { purge, adapter });
        tabs(root).find((tab) => tab.dataset.tab === 'data')!.click();
        await settle();
        root.querySelector<HTMLButtonElement>('[data-purge-price]')!.click();
        await settle();
        expect(root.querySelector('[data-purge-go]')).not.toBeNull();
        root.querySelector<HTMLElement>('[data-plugin-pane-switch="mcphealth"]')!.click();
        await settle();
        expect(root.querySelector('[data-plugin-state]')?.getAttribute('data-plugin-state')).toBe('active');
        expect(root.querySelector('[data-purge-confirm]')).toBeNull();
        expect(root.querySelector('[data-purge-go]')).toBeNull();
        expect(root.querySelector<HTMLButtonElement>('[data-purge-price]')!.disabled).toBe(true);
        expect(purge.mock.calls).toEqual([['mcphealth', undefined]]);
    });
});

describe('the pane model', () => {
    test('surface chips count what the plugin adds, in the card\'s words', () => {
        expect(surfaceChips(SWARM.surfaces!, t).map((c) => [c.key, c.label, c.count])).toEqual([
            ['tabs', 'tab', 1], ['mcp_tools', 'mcp tools', 3], ['topics', 'live updates', 1],
        ]);
        expect(surfaceChips({}, t)).toEqual([]);
    });

    test('bytes read as kb, mb or gb, and a size the server did not send is no badge', () => {
        expect(bytesText(2048, t)).toBe('2 kb');
        expect(bytesText(3_500_000, t)).toBe('3.3 mb');
        const item = toCplugItem({ ...SWARM, storage_bytes: undefined }, t);
        expect(paneTabs(item, t).find((tab) => tab.id === 'data')?.badge).toBeNull();
    });

    test('the reason is null unless held or waiting, and purge is blocked unless off or removed', () => {
        expect(paneReason(toCplugItem(SWARM, t), t)).toBeNull();
        expect(paneReason(toCplugItem({ ...SWARM, state: 'unavailable' }, t), t)?.more).toBe('turn it off and on to try again.');
        expect(purgeBlocked(toCplugItem(MCP, t), t)).toBeNull();
        expect(purgeBlocked(toCplugItem({ id: 'gone', enabled: false, state: 'removed' }, t), t)).toBeNull();
        expect(purgeBlocked(toCplugItem({ ...SWARM, tier: 'core', name_key: undefined }, t), t)).toContain('part of the app');
    });
});

describe('an off plugin that needs the owner\'s consent (#2572)', () => {
    const SIDELOAD: CplugRow = {
        ...MCP, id: 'flowview', tier: 'sideload', consent_required: true, permissions: { app: ['flow.read'] }, needs: ['flow.read'],
        risks: { 'flow.read': 'medium' },
    };
    const sheetOf = (names: string[]): CplugSheet => ({
        digest: 'seen-digest', body_sha: 'b', grants_sha: 'g', permissions: names.map((name) => ({ name, risk: 'medium', granted: false })),
    });
    const loadSheet = async (): Promise<CplugSheet> => sheetOf(['flow.read']);

    async function openPermissions(root: HTMLElement): Promise<void> {
        tabs(root).find((tab) => tab.dataset.tab === 'permissions')!.click();
        await settle();
    }

    test('the sheet draws an untouched tick and a grant button that stays off until the owner ticks, then sends the tick, the sheet read and turn-on', async () => {
        const grant = vi.fn(async () => ({}));
        const root = await openPane([SIDELOAD], 'flowview', { grant, loadSheet });
        await openPermissions(root);
        const tick = root.querySelector<HTMLInputElement>('[data-perm-tick="flow.read"]')!;
        const button = root.querySelector<HTMLButtonElement>('[data-cplug-grant]')!;
        expect(tick.checked, 'never pre-ticked').toBe(false);
        expect(button.disabled).toBe(true);
        expect(button.textContent).toBe('grant 1 and turn on');
        tick.click();
        await settle();
        button.click();
        await settle();
        expect(grant).toHaveBeenCalledExactlyOnceWith('flowview', ['flow.read'], { enable: true, seen: sheetOf(['flow.read']) });
    });

    test('new code under the same plugin clears the ticks: a re-read sheet with another digest leaves the button off (#2572)', async () => {
        let n = 0;
        const reads = vi.fn(async (): Promise<CplugSheet> => ({ ...sheetOf(['flow.read']), digest: `digest-${(n += 1)}` }));
        const grant = vi.fn(async () => ({}));
        const root = await openPane([SIDELOAD], 'flowview', { grant, loadSheet: reads });
        await openPermissions(root);
        root.querySelector<HTMLInputElement>('[data-perm-tick="flow.read"]')!.click();
        await settle();
        root.querySelector<HTMLButtonElement>('[data-cplug-grant]')!.click();
        await settle();
        expect(reads.mock.calls.length).toBeGreaterThan(1);
        expect(root.querySelector<HTMLInputElement>('[data-perm-tick="flow.read"]')!.checked).toBe(false);
        expect(root.querySelector<HTMLButtonElement>('[data-cplug-grant]')!.disabled).toBe(true);
    });

    test('with two medium permissions the button stays off until both are ticked', async () => {
        const two: CplugRow = { ...SIDELOAD, permissions: { app: ['flow.read', 'flow.write'] }, needs: ['flow.read', 'flow.write'], risks: { 'flow.read': 'medium', 'flow.write': 'medium' } };
        const root = await openPane([two], 'flowview', { grant: vi.fn(), loadSheet });
        await openPermissions(root);
        const button = root.querySelector<HTMLButtonElement>('[data-cplug-grant]')!;
        root.querySelector<HTMLInputElement>('[data-perm-tick="flow.read"]')!.click();
        await settle();
        expect(button.disabled).toBe(true);
        root.querySelector<HTMLInputElement>('[data-perm-tick="flow.write"]')!.click();
        await settle();
        expect(button.disabled).toBe(false);
    });

    test('a refused grant shows the refusal in the pane, holds the button while it runs and frees it after', async () => {
        let reject: (e: Error) => void = () => {};
        const grant = vi.fn(() => new Promise<never>((_, no) => { reject = no; }));
        const root = await openPane([SIDELOAD], 'flowview', { grant, loadSheet });
        await openPermissions(root);
        root.querySelector<HTMLInputElement>('[data-perm-tick="flow.read"]')!.click();
        await settle();
        const button = root.querySelector<HTMLButtonElement>('[data-cplug-grant]')!;
        button.click();
        await settle();
        expect(button.disabled, 'held while in flight').toBe(true);
        button.click();
        expect(grant).toHaveBeenCalledTimes(1);
        reject(new Error('cannot be turned on: needs task manager, which this build lacks'));
        await settle();
        expect(root.querySelector('[data-plugin-pane-error]')?.textContent).toContain('needs task manager');
        expect(button.disabled).toBe(false);
    });

    test('a first-party plugin that is off draws no tick and no grant button', async () => {
        const root = await openPane([MCP], 'mcphealth', { loadSheet });
        await openPermissions(root);
        expect(root.querySelector('[data-perm-tick]')).toBeNull();
        expect(root.querySelector('[data-cplug-grant]')).toBeNull();
    });
});
