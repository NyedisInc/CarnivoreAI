/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

vi.mock('../../opscenter/api/auth.svelte', () => ({
    auth: { state: 'signed-in' },
    initAuth: async () => {},
    ApiError: class ApiError extends Error {},
    authFetch: async () => null,
}));

import PipelineStatusPanel from './PipelineStatusPanel.svelte';
import { setLocale } from '../i18n/index.svelte';
import type { Fetcher, PipelineStatus } from './api';
import { REGISTRY } from '../../opscenter/cells/registry';
import { META } from '../../opscenter/engine/meta';
import { resetLayout } from '../../opscenter/engine/model';
import { validate } from '../../opscenter/engine/persist';
import { dropRetiredCells } from '../../opscenter/engine/retired-cells';
import { v7Layout } from '../../opscenter/engine/v7/fixtures/v7-layouts';
import type { Layout, RowModel } from '../../opscenter/engine/types';
import widgets from '../../../../src/data/widgets.json';

setLocale('en');

const plugin = (files: number, over: Record<string, unknown> = {}) =>
    ({ lag: { files, seconds: files ? 90 : 0 }, failures: 0, last_error: null, rebuilding: false, last_delivery_at: null, runs: 0, ...over });

function status(over: Partial<PipelineStatus> = {}): PipelineStatus {
    return {
        state: 'caught_up', lag: { files: 0, seconds: 0 }, last_delivery_at: null, stalled_since: null, rebuilding: [],
        plugins: { stats: plugin(0), deepsearch: plugin(0) }, ...over,
    } as PipelineStatus;
}

interface Call { path: string; method: string }

function harness(body: () => PipelineStatus) {
    const calls: Call[] = [];
    const fetcher = (async (path: string, init?: RequestInit) => {
        calls.push({ path, method: init?.method ?? 'GET' });
        return path === '/pipeline/status' ? body() : { plugin: 'stats', dropped_bytes: 1, files_marked: 2 };
    }) as unknown as Fetcher;
    return { fetcher, calls };
}

const apps: ReturnType<typeof mount>[] = [];
beforeEach(() => { document.body.innerHTML = ''; });
afterEach(() => { for (const app of apps.splice(0)) unmount(app); document.body.innerHTML = ''; });

async function settle(): Promise<void> {
    for (let i = 0; i < 10; i += 1) { await Promise.resolve(); await tick(); }
    flushSync();
}

async function render(fetcher: Fetcher): Promise<HTMLElement> {
    const target = document.createElement('div');
    document.body.appendChild(target);
    apps.push(mount(PipelineStatusPanel, { target, props: { fetcher } }));
    await settle();
    return target;
}

const line = (target: HTMLElement): string => target.querySelector('[data-ps="line"]')?.textContent?.replace(/\s+/g, ' ').trim() ?? '';

describe('the status line', () => {
    test.each([
        ['caught_up', status(), /^caught up$/, 'ok'],
        ['behind', status({ state: 'behind', lag: { files: 12, seconds: 683 } }), /^behind: 12 files, 11m 23s$/, 'wait'],
        ['stalled', status({ state: 'stalled', stalled_since: Date.now() / 1000 - 3600 }), /^stalled since \S+/, 'bad'],
        ['rebuilding', status({ state: 'rebuilding', rebuilding: ['deepsearch'], plugins: { stats: plugin(0), deepsearch: plugin(5, { rebuilding: true }) } }), /^rebuilding deep search$/, 'wait'],
        ['off', status({ state: 'off', plugins: {} }), /^the pipeline is not running$/, 'off'],
    ] as const)('state %s reads its own words and tone', async (state, body, words, tone) => {
        const target = await render(harness(() => body).fetcher);
        const row = target.querySelector('[data-ps="line"]');
        expect(row, 'the line is drawn').not.toBeNull();
        expect(row!.getAttribute('data-ps-state')).toBe(state);
        expect(row!.querySelector('[data-ps="state"]')?.textContent?.trim()).toMatch(words);
        expect(row!.querySelector('[data-ps="state"]')?.className).toContain(`ps-state--${tone}`);
    });

    test('one row per plugin the engine names, each with its own lag and a rebuild button', async () => {
        const target = await render(harness(() => status({ state: 'behind', lag: { files: 3, seconds: 5 }, plugins: { stats: plugin(0), deepsearch: plugin(3) } })).fetcher);
        const rows = [...target.querySelectorAll('[data-ps-plugin]')];
        expect(rows.map((row) => row.getAttribute('data-ps-plugin'))).toEqual(['stats', 'deepsearch']);
        expect(rows[0]!.querySelector('[data-ps="lag"]')?.textContent).toBe('caught up');
        expect(rows[1]!.querySelector('[data-ps="lag"]')?.textContent).toBe('3 files waiting');
        expect(rows.every((row) => row.querySelector('[data-ps="rebuild"]') !== null)).toBe(true);
    });

    test('a failing plugin shows why in the panel only (the log has the rest), never as an alert', async () => {
        const target = await render(harness(() => status({ plugins: { stats: plugin(0, { failures: 1, last_error: 'OperationalError' }), deepsearch: plugin(0) } })).fetcher);
        expect(target.querySelector('[data-ps-plugin="stats"] [data-ps="failing"]')?.textContent).toContain('OperationalError');
        expect(target.querySelector('[data-ps-plugin="deepsearch"] [data-ps="failing"]')).toBeNull();
    });

    test('rebuild asks first, cancel posts nothing, confirm posts to the plugin route once', async () => {
        const { fetcher, calls } = harness(() => status());
        const target = await render(fetcher);
        const button = () => target.querySelector('[data-ps-plugin="stats"] [data-ps="rebuild"]') as HTMLElement;
        button().click();
        await settle();
        expect(target.querySelector('[data-ps="rebuild-panel"]')).not.toBeNull();
        (target.querySelector('[data-ps="cancel"]') as HTMLElement).click();
        await settle();
        expect(target.querySelector('[data-ps="rebuild-panel"]')).toBeNull();
        expect(calls.filter((call) => call.method === 'POST')).toEqual([]);
        button().click();
        await settle();
        (target.querySelector('[data-ps="confirm"]') as HTMLElement).click();
        await settle();
        expect(calls.filter((call) => call.method === 'POST')).toEqual([{ path: '/pipeline/plugins/stats/rebuild', method: 'POST' }]);
        expect(target.querySelector('[data-ps="note"]')?.textContent).toBe('rebuild started.');
    });
});

describe('the removed save pipeline widget and the restored pipeline widget', () => {
    const REMOVED = ['save-pipeline'];
    const clone = <T,>(value: T): T => JSON.parse(JSON.stringify(value)) as T;
    const ids = (layout: Layout) => layout.rows.flatMap((row) => row.slots.map((slot) => slot.id as string));

    function withWidgets(page: 'home' | 'terminal'): Layout {
        const base = resetLayout(META, page);
        const band: RowModel = { id: 'r9', kind: 'px', size: 200, slots: [{ id: 'save-pipeline' as never, fr: 1 }] };
        return { ...base, rows: page === 'home' ? [...base.rows, band] : base.rows, hidden: [...base.hidden, ...REMOVED as never[]] };
    }

    test('the build registers the pipeline widget (global, off the surface) and not the save pipeline', () => {
        expect(Object.keys(META)).toContain('pipeline');
        expect(Object.keys(REGISTRY)).toContain('pipeline');
        expect(resetLayout(META, 'home').hidden).toContain('pipeline');
        expect((widgets as { widgets: { id: string }[] }).widgets.map((w) => w.id)).toContain('core.pipeline');
        for (const id of REMOVED) {
            expect(Object.keys(META)).not.toContain(id);
            expect(Object.keys(REGISTRY)).not.toContain(id);
            expect((widgets as { widgets: { id: string }[] }).widgets.map((w) => w.id)).not.toContain(`core.${id}`);
        }
    });

    test('a saved Home naming the save pipeline opens without it, with no refusal, and keeps every other row', () => {
        const now = resetLayout(META, 'home');
        const checked = validate(clone(withWidgets('home')), META, 'home');
        expect(checked.refusal).toBeNull();
        expect(checked.migrated).toBe(true);
        expect(ids(checked.layout!)).not.toContain('save-pipeline');
        expect(checked.layout!.hidden).not.toContain('save-pipeline');
        expect(checked.layout!.hidden).toContain('pipeline');
        expect(checked.layout!.rows).toEqual(clone(now.rows));
    });

    test('a terminal page layout naming it in its hidden list opens too', () => {
        const checked = validate(clone(withWidgets('terminal')), META, 'terminal');
        expect(checked.refusal).toBeNull();
        expect(checked.migrated).toBe(true);
        expect(checked.layout!.hidden).not.toContain('save-pipeline');
    });

    test('a v7 tree naming it opens without it', () => {
        const doc = v7Layout('homeWithSavePipeline');
        expect(JSON.stringify(doc)).toContain('"id":"save-pipeline"');
        const checked = validate(doc, META, 'home');
        expect(checked.refusal).toBeNull();
        expect(ids(checked.layout!)).not.toContain('save-pipeline');
    });

    test('nothing is written back here and a second read is a no-op', () => {
        const once = dropRetiredCells(clone(withWidgets('home')), 'home');
        expect(once.migrated).toBe(true);
        expect(dropRetiredCells(once.raw, 'home')).toEqual({ raw: once.raw, migrated: false });
    });
});
