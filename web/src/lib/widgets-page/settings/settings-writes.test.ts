/** @vitest-environment jsdom */
import { beforeEach, describe, expect, test } from 'vitest';
import { widgetBars } from '../../widget-bars/bar-settings.svelte';
import { t } from '../../i18n/index.svelte';
import { applyPick, resetWithUndo, type Pick } from './settings-writes';
import type { BarOp } from './settings-model';

type Toast = { title: string; action_label?: string; on_action?: () => void; alert_severity?: string };
const g = globalThis as Record<string, unknown>;
let shared: Record<string, unknown>;
let log: string[];
let gates: (() => void)[];
let statuses: string[];
let toasts: Toast[];
let batches: string[][];
let server: unknown;
let discarded: string[];

let hold = false;
beforeEach(() => {
    shared = {};
    log = [];
    gates = [];
    statuses = [];
    toasts = [];
    batches = [];
    server = null;
    discarded = [];
    hold = false;
    g.PreferenceBridge = {
        read: (field: string) => shared[field] ?? null,
        write: async (field: string, value: unknown) => {
            log.push(JSON.stringify(value));
            if (hold) await new Promise<void>((resolve) => gates.push(resolve));
            const status = statuses.shift() ?? 'committed';
            if (status === 'committed') shared[field] = value;
            return { status };
        },
        writeMany: async (entries: { field: string; value: unknown }[]) => {
            batches.push(entries.map((e) => e.field));
            for (const e of entries) shared[e.field] = e.value;
            return { status: statuses.shift() ?? 'committed' };
        },
        follow: () => () => {},
    };
    g.Preferences = { committedValue: () => server, discardLocal: (field: string) => discarded.push(field), adopt: () => {} };
    g.ToastManager = { add: (toast: Toast) => toasts.push(toast), dismiss: () => {} };
    widgetBars.reload();
});

const flush = async (): Promise<void> => { for (let i = 0; i < 12; i += 1) await new Promise((resolve) => setTimeout(resolve, 0)); };
const release = async (): Promise<void> => { gates.shift()?.(); await flush(); };
const size = (edge: 'side' | 'bottom', value: 'compact' | 'detailed', text = `${edge} ${value}`): Pick => () => ({ ops: [{ kind: 'bar', edge, patch: { size: value } }], text });
const last = (): Toast => toasts.at(-1)!;

describe('settling', () => {
    test('a write that settles late still ends in the saved toast, with an undo', async () => {
        hold = true;
        const done = applyPick('size:side', size('side', 'detailed', 'saved it'), t);
        await flush();
        expect(toasts).toHaveLength(0);
        await release();
        await done;
        expect(last().title).toBe('saved it');
        expect(last().action_label).toBe('undo');
    });

    test('a 409 replays the pick over the server value and still ends saved', async () => {
        statuses = ['stale_revision', 'committed'];
        server = { v: 1, bottom: { size: 'compact' } };
        await applyPick('size:side', size('side', 'detailed', 'saved it'), t);
        expect(log).toEqual([JSON.stringify({ v: 1, side: { size: 'detailed' } }), JSON.stringify({ v: 1, bottom: { size: 'compact' }, side: { size: 'detailed' } })]);
        expect(last().title).toBe('saved it');
    });

    test('a second refusal says it changed on another device, with no undo and no retry', async () => {
        statuses = ['stale_revision', 'stale_revision'];
        await applyPick('size:side', size('side', 'detailed'), t);
        expect(last().title).toBe(t('widgets.settings.toast.conflict'));
        expect(last().action_label).toBeUndefined();
    });

    test('a failed write offers a retry that runs the pick again and ends saved', async () => {
        statuses = ['failed'];
        await applyPick('size:side', size('side', 'detailed', 'saved it'), t);
        expect(last().title).toBe(t('widgets.page.toast.failed'));
        expect(last().action_label).toBe('retry');
        last().on_action!();
        await flush();
        expect(last().title).toBe('saved it');
    });
});

describe('undo', () => {
    test('undo writes the prior leaf back and says undone', async () => {
        await applyPick('size:side', size('side', 'detailed'), t);
        last().on_action!();
        await flush();
        expect(shared['widget_bars'] ?? null).toBeNull();
        expect(last().title).toBe(t('widgets.page.toast.undone'));
    });

    test('an undo that fails on its first step offers a retry', async () => {
        await applyPick('size:side', size('side', 'detailed'), t);
        statuses = ['failed'];
        last().on_action!();
        await flush();
        expect(last().action_label).toBe('retry');
        last().on_action!();
        await flush();
        expect(last().title).toBe(t('widgets.page.toast.undone'));
    });

    test('an undo that lands one step and fails the next says so and offers no retry', async () => {
        const both: Pick = () => ({ ops: [{ kind: 'bar', edge: 'side', patch: { show: false } }, { kind: 'bar', edge: 'bottom', patch: { show: false } }] as BarOp[], text: 'hid both' });
        await applyPick('show', both, t);
        statuses = ['committed', 'failed'];
        last().on_action!();
        await flush();
        expect(last().title).toBe(t('widgets.settings.toast.undo_partial'));
        expect(last().action_label).toBeUndefined();
    });
});

describe('the queue', () => {
    test('writes run in press order, each only after the one before settled', async () => {
        hold = true;
        const a = applyPick('size:side', size('side', 'detailed'), t);
        const b = applyPick('size:bottom', size('bottom', 'compact'), t);
        await flush();
        expect(log).toHaveLength(1);
        await release();
        await a;
        await flush();
        expect(log).toHaveLength(2);
        await release();
        await b;
        expect(log[0]).toContain('"side"');
        expect(log[1]).toContain('"bottom"');
    });

    test('presses of one strip that are still waiting collapse to the last: one write, one toast', async () => {
        hold = true;
        const first = applyPick('size:side', size('side', 'detailed', 'first'), t);
        const second = applyPick('size:bottom', size('bottom', 'compact', 'second'), t);
        const third = applyPick('size:bottom', size('bottom', 'detailed', 'third'), t);
        await flush();
        await release();
        await first;
        await flush();
        await release();
        await Promise.all([second, third]);
        expect(log).toHaveLength(2);
        expect(log[1]).toContain('"detailed"');
        expect(toasts.map((x) => x.title)).toEqual(['first', 'third']);
    });
});

describe('reset', () => {
    test('undo writes all three fields back in ONE write, an absent one back absent', async () => {
        shared['widget_bars'] = { v: 1, bottom: { size: 'compact' } };
        shared['session_rail'] = { v: 1, items: [{ widget: 'core.files' }] };
        widgetBars.reload();
        g.API = { call: async () => { shared['widget_bars'] = null; shared['session_rail'] = null; return { status: 'committed' }; } };
        await resetWithUndo(t);
        expect(last().title).toBe(t('widgets.settings.toast.reset'));
        last().on_action!();
        await flush();
        expect(batches).toEqual([['widget_bars', 'session_rail', 'session_rail_bottom']]);
        expect(shared['widget_bars']).toEqual({ v: 1, bottom: { size: 'compact' } });
        expect(shared['session_rail']).toEqual({ v: 1, items: [{ widget: 'core.files' }] });
        expect(shared['session_rail_bottom']).toBeNull();
        expect(last().title).toBe(t('widgets.page.toast.undone'));
    });

    test('an undo whose combined write is refused (409) discards the unsaved local values and offers a retry', async () => {
        shared['widget_bars'] = { v: 1, bottom: { size: 'compact' } };
        widgetBars.reload();
        g.API = { call: async () => { shared['widget_bars'] = null; return { status: 'committed' }; } };
        await resetWithUndo(t);
        statuses = ['stale_revision'];
        last().on_action!();
        await flush();
        expect(discarded).toEqual(['widget_bars', 'session_rail', 'session_rail_bottom']);
        expect(last().title).toBe(t('widgets.page.toast.failed'));
        expect(last().action_label).toBe('retry');
    });
});

describe('a thrown error', () => {
    test('is logged and does not wedge the queue: the next write still runs', async () => {
        const original = (g.PreferenceBridge as { write: unknown }).write;
        (g.PreferenceBridge as { write: unknown }).write = async () => { throw new Error('boom'); };
        await applyPick('size:side', size('side', 'detailed'), t);
        (g.PreferenceBridge as { write: unknown }).write = original;
        await applyPick('size:bottom', size('bottom', 'compact', 'second'), t);
        expect(last().title).toBe('second');
    });
});
