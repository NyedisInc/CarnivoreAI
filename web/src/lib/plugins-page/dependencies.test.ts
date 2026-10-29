/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

import PluginsScreen from './PluginsScreen.svelte';
import { ApiError } from '../../opscenter/api/auth.svelte';
import { createCplugsAdapter, dependencyRefusal, dependencyView, setCplugEnabled, toCplugItem, type CplugRow } from './cplugs-adapter';
import { createI18n } from '../../../../client/js/i18n/runtime.js';
import type { Translate } from '../sessions/types';

const en = createI18n({ locale: 'en' }) as { t: Translate };
const t: Translate = (key, params) => en.t(key, params);

const FLOW: CplugRow = {
    id: 'flow', name_key: 'cplug.flow.name', description_key: 'cplug.flow.description', version: '1.0.0', tier: 'builtin',
    enabled: true, state: 'active', permissions: { app: [] }, revision: 2,
    dependencies: {
        plugins: [{ id: 'huddle', status: 'on' }, { id: 'save', status: 'off' }],
        core: [{ id: 'crosstalk', available: true }, { id: 'transcript_events', available: false }],
        min_app_version: { need: '1.16.0', have: '1.16.1', met: true },
        needed_by: [],
        enabled_dependents: [],
    },
};
const SAVE: CplugRow = {
    id: 'save', name_key: 'cplug.save.name', description_key: 'cplug.save.description', version: '1.0.0', tier: 'builtin',
    enabled: true, state: 'active', permissions: { app: [] }, revision: 5,
    dependencies: { needed_by: [{ id: 'nudge', enabled: true }, { id: 'deepsearch', enabled: false }], enabled_dependents: ['nudge'] },
};

describe('dependencyView', () => {
    test('marks each need ok, off or missing and words it', () => {
        const view = dependencyView(FLOW, t);
        expect(view.needs.map((n) => [n.kind, n.id, n.status])).toEqual([
            ['plugin', 'huddle', 'ok'], ['plugin', 'save', 'off'], ['core', 'crosstalk', 'ok'], ['core', 'transcript_events', 'missing'],
            ['version', 'min_app_version', 'ok'],
        ]);
        expect(view.needs.find((n) => n.id === 'min_app_version')!.label).toBe('app version 1.16.0 or newer');
        for (const need of view.needs) expect(need.label).not.toContain('plugins.page');
    });

    test('an unmet version is missing, and a row from an older server has no needs', () => {
        const old = dependencyView({ ...FLOW, dependencies: { min_app_version: { need: '1.16.0', have: '1.12.0', met: false } } }, t);
        expect(old.needs.map((n) => n.status)).toEqual(['missing']);
        expect(dependencyView({ ...FLOW, dependencies: undefined }, t)).toEqual({ needs: [], neededBy: [], enabledDependents: [] });
    });

    test('needed by names each dependent and whether it is on', () => {
        const view = dependencyView(SAVE, t);
        expect(view.neededBy.map((n) => [n.id, n.enabled])).toEqual([['nudge', true], ['deepsearch', false]]);
        expect(view.enabledDependents).toHaveLength(1);
    });
});

describe('the refusals in the page words', () => {
    const refusal = (detail: Record<string, unknown>) => new ApiError('x', 409, null, { detail });

    test('requirements_unmet names the missing feature and the version', () => {
        const message = dependencyRefusal(
            refusal({ code: 'requirements_unmet', unmet: { core: ['crosstalk'], min_app_version: { need: '1.16.0', have: '1.15.0' } } }), t,
        ).message;
        expect(message).toContain('cannot be turned on');
        expect(message).toContain('crosstalk');
        expect(message).toContain('1.16.0');
        expect(message).toContain('1.15.0');
    });

    test('has_dependents names the plugins, and any other error passes through', () => {
        expect(dependencyRefusal(refusal({ code: 'has_dependents', dependents: ['nudge'] }), t).message).toContain('cannot be turned off yet');
        const other = new Error('boom');
        expect(dependencyRefusal(other, t)).toBe(other);
        expect(dependencyRefusal(new ApiError('x', 500, null, null), t).message).toBe('x');
    });
});

describe('the switch-off and its confirmation on the wire', () => {
    function server() {
        const puts: Array<Record<string, unknown>> = [];
        const fetcher = vi.fn(async (_path: string, init: RequestInit = {}) => {
            if (!init.method) return SAVE;
            const body = JSON.parse(String(init.body));
            puts.push(body);
            if (!body.confirm_dependents) {
                throw new ApiError('x', 409, null, { detail: { code: 'has_dependents', dependents: ['nudge'] } });
            }
            return { ...SAVE, enabled: false, state: 'disabled' };
        });
        return { puts, fetcher: fetcher as never };
    }

    test('an unconfirmed switch-off is refused in words; a confirmed one sends confirm_dependents once', async () => {
        const { puts, fetcher } = server();
        await expect(setCplugEnabled('cplug:save', false, t, fetcher, async () => {})).rejects.toThrow(/cannot be turned off yet/);
        const adapter = createCplugsAdapter(t, fetcher, async () => {});
        adapter.confirmDependents('cplug:save');
        const row = await adapter.setEnabled!('cplug:save', false);
        expect(row.enabled).toBe(false);
        expect(puts.map((p) => p.confirm_dependents ?? null)).toEqual([null, true]);
        await expect(adapter.setEnabled!('cplug:save', false)).rejects.toThrow(/cannot be turned off yet/);
    });

    test('turning ON never sends confirm_dependents', async () => {
        const puts: Array<Record<string, unknown>> = [];
        const fetcher = (async (_p: string, init: RequestInit = {}) => {
            if (init.method) puts.push(JSON.parse(String(init.body)));
            return { ...SAVE, enabled: false, state: 'disabled' };
        }) as never;
        await setCplugEnabled('cplug:save', true, t, fetcher, async () => {}, true);
        expect(puts[0]).not.toHaveProperty('confirm_dependents');
    });
});

describe('the pane and the confirm', () => {
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
            await new Promise((resolve) => setTimeout(resolve, 0));
        }
        flushSync();
    }

    async function show(rows: CplugRow[], calls: Array<[string, boolean]>, confirmed: string[]): Promise<HTMLElement> {
        const target = document.createElement('div');
        document.body.append(target);
        const adapter = {
            list: async () => rows.map((row) => toCplugItem(row, t)),
            setEnabled: async (id: string, enabled: boolean) => {
                calls.push([id, enabled]);
                return toCplugItem({ ...rows.find((r) => `cplug:${r.id}` === id)!, enabled, state: enabled ? 'active' : 'disabled' }, t);
            },
            confirmDependents: (id: string) => void confirmed.push(id),
        };
        mounted = mount(PluginsScreen, { target, props: { embedded: true, adapter, t, loadActivity: async () => [] } });
        await settle();
        return target;
    }

    const open = (root: HTMLElement, name: string) =>
        Array.from(root.querySelectorAll<HTMLButtonElement>('.catalog-card__open')).find((el) => el.textContent?.includes(name))!.click();

    test("flow's pane lists its needs and marks each one", async () => {
        const root = await show([FLOW, SAVE], [], []);
        open(root, 'flow chart');
        await settle();
        const needs = Array.from(root.querySelectorAll<HTMLElement>('[data-cplug-needs] [data-need-id]'));
        expect(needs.map((el) => [el.dataset.needId, el.dataset.needStatus])).toEqual([
            ['huddle', 'ok'], ['save', 'off'], ['crosstalk', 'ok'], ['transcript_events', 'missing'], ['min_app_version', 'ok'],
        ]);
        expect(root.querySelectorAll('[data-cplug-needed-by] [data-needed-by-id]')).toHaveLength(0);
        expect(root.querySelector('[data-cplug-needed-by]')?.textContent).toContain('no plugin needs flow chart');
    });

    test("the pane's own switch asks first too, under the title strip, and confirm switches it off once confirmed", async () => {
        const calls: Array<[string, boolean]> = [];
        const confirmed: string[] = [];
        const root = await show([FLOW, SAVE], calls, confirmed);
        open(root, 'conversation backups');
        await settle();
        root.querySelector<HTMLButtonElement>('[data-plugin-pane-switch="save"]')!.click();
        await settle();
        const ask = root.querySelector<HTMLElement>('.oc-page__detail [data-cplug-disable-ask]');
        expect(ask, 'the confirm is in the pane').not.toBeNull();
        expect(ask!.compareDocumentPosition(root.querySelector('.oc-page__detail [role="tablist"]')!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
        expect(calls).toEqual([]);
        root.querySelector<HTMLButtonElement>('[data-cplug-disable-confirm]')!.click();
        await settle();
        expect(confirmed).toEqual(['cplug:save']);
        expect(calls).toEqual([['cplug:save', false]]);
    });

    test('the pane of a needed plugin lists who needs it', async () => {
        const root = await show([FLOW, SAVE], [], []);
        open(root, 'conversation backups');
        await settle();
        const by = Array.from(root.querySelectorAll<HTMLElement>('[data-cplug-needed-by] [data-needed-by-id]'));
        expect(by.map((el) => [el.dataset.neededById, el.dataset.neededByEnabled])).toEqual([['nudge', 'true'], ['deepsearch', 'false']]);
    });

    test('switching off a plugin enabled plugins need asks first; cancel changes nothing, confirm switches it off once confirmed', async () => {
        const calls: Array<[string, boolean]> = [];
        const confirmed: string[] = [];
        const root = await show([FLOW, SAVE], calls, confirmed);
        const card = root.querySelector<HTMLElement>('[data-item-id="cplug:save"]')!;
        card.querySelector<HTMLButtonElement>('[role="switch"]')!.click();
        await settle();
        const confirm = root.querySelector<HTMLElement>('[data-cplug-disable-ask]');
        expect(confirm).not.toBeNull();
        expect(root.querySelector('[data-cplug-dependents]')!.textContent).toContain('need conversation backups');
        expect(calls).toEqual([]);
        root.querySelector<HTMLButtonElement>('[data-cplug-disable-cancel]')!.click();
        await settle();
        expect(root.querySelector('[data-cplug-disable-ask]')).toBeNull();
        expect(calls).toEqual([]);
        root.querySelector<HTMLElement>('[data-item-id="cplug:save"] [role="switch"]')!.click();
        await settle();
        root.querySelector<HTMLButtonElement>('[data-cplug-disable-confirm]')!.click();
        await settle();
        expect(confirmed).toEqual(['cplug:save']);
        expect(calls).toEqual([['cplug:save', false]]);
    });

    test('a plugin nothing enabled needs switches straight off with no confirm', async () => {
        const calls: Array<[string, boolean]> = [];
        const root = await show([FLOW, SAVE], calls, []);
        root.querySelector<HTMLElement>('[data-item-id="cplug:flow"] [role="switch"]')!.click();
        await settle();
        expect(root.querySelector('[data-cplug-disable-ask]')).toBeNull();
        expect(calls).toEqual([['cplug:flow', false]]);
    });
});
