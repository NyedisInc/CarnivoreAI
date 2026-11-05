/** @vitest-environment jsdom */
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

import BarsEditor from './BarsEditor.svelte';
import { railStores } from '../../session-rail/rail-store.svelte';
import { widgetBars } from '../../widget-bars/bar-settings.svelte';
import { SAVE_WAIT_MS } from '../save-outcome';
import { closeToast } from '../undo-toast';
import { t } from '../../i18n/index.svelte';
import { stubResizeObserver } from './mock-test-support';

type Listener = (name: string, value: unknown, record: { state?: string }) => void;
type Verdict = 'committed' | 'conflict' | 'failed';

const g = globalThis as Record<string, unknown>;
const SIDE = 'session_rail';
const BOTTOM = 'session_rail_bottom';
let shared: Record<string, unknown>;
let kept: Record<string, unknown>;
let listeners: Set<Listener>;
let writes: string[][];
let verdict: Verdict | 'hang';
let toasts: Record<string, unknown>[];
let mounted: Record<string, unknown> | null = null;

const emit = (field: string, state: string): void => { for (const listener of [...listeners]) listener(field, null, { state }); };

async function save(entries: { field: string; value: unknown }[]): Promise<unknown> {
    writes.push(entries.map((entry) => entry.field));
    for (const entry of entries) emit(entry.field, 'pending');
    if (verdict === 'hang') return new Promise(() => {});
    if (verdict === 'committed') for (const entry of entries) shared[entry.field] = entry.value;
    if (verdict === 'conflict') for (const entry of entries) kept[entry.field] = entry.value;
    for (const entry of entries) emit(entry.field, verdict);
    return { status: verdict };
}

beforeEach(() => {
    stubResizeObserver();
    shared = {
        [SIDE]: { v: 2, sections: [{ items: [{ widget: 'core.notes' }, { widget: 'core.files' }] }] },
        [BOTTOM]: { v: 2, sections: [{ items: [{ widget: 'core.shell' }] }] },
    };
    kept = {};
    listeners = new Set();
    writes = [];
    verdict = 'committed';
    toasts = [];
    g.PreferenceBridge = {
        read: (field: string) => (field in kept ? kept[field] : shared[field]) ?? null,
        write: (field: string, value: unknown) => save([{ field, value }]),
        writeMany: (entries: { field: string; value: unknown }[]) => save(entries),
        follow: () => () => {},
    };
    g.Preferences = {
        subscribe: (listener: Listener) => { listeners.add(listener); return () => listeners.delete(listener); },
        stateFor: () => '',
        discardLocal: (field: string) => { delete kept[field]; },
    };
    g.ToastManager = { add: (toast: Record<string, unknown>) => toasts.push(toast), dismiss: () => {} };
    closeToast();
    railStores.side.reload();
    railStores.bottom.reload();
    widgetBars.reload();
});
afterEach(() => {
    if (mounted) unmount(mounted);
    mounted = null;
    document.body.innerHTML = '';
    vi.useRealTimers();
});

async function settle(): Promise<void> {
    for (let i = 0; i < 10; i += 1) await Promise.resolve();
    await tick();
    flushSync();
}
async function show(): Promise<void> {
    mounted = mount(BarsEditor, { target: document.body, props: { t } });
    await settle();
}
const key = (name: string): HTMLButtonElement => document.querySelector<HTMLButtonElement>(`.wp-key[aria-label="${name}"]`)!;
const button = (k: string): HTMLButtonElement | null => document.querySelector<HTMLButtonElement>(`[data-k=${k}]`);
const items = (edge: 'side' | 'bottom'): string[] => railStores[edge].items.map((item) => item.widget);
const lastToast = (): Record<string, unknown> => toasts.at(-1)!;

describe('BarsEditor', () => {
    test('shows the real keys of both bars, named by their widgets, and nothing is selected', async () => {
        await show();
        expect([...document.querySelectorAll('.wp-mockbar--side .wp-key')].map((el) => el.getAttribute('aria-label'))).toEqual(['notes', 'files']);
        expect([...document.querySelectorAll('.wp-mockbar--bottom .wp-key')].map((el) => el.getAttribute('aria-label'))).toEqual(['terminal']);
        expect(button('edit-move')).toBeNull();
        expect(document.querySelector('.wp-edit__hint')?.textContent).toBe('select a key to move it or take it out');
    });

    test('the coarse-pointer key list holds every key as a base row button and shares the frame\'s selection and actions', async () => {
        await show();
        const rows = [...document.querySelectorAll<HTMLButtonElement>('[data-k=edit-key]')];
        expect(rows.map((el) => el.textContent?.trim())).toEqual(['right bar: notes', 'right bar: files', 'bottom bar: terminal']);
        expect(rows.every((el) => el.getAttribute('data-btn') === 'row')).toBe(true);
        rows[1]!.click();
        await settle();
        expect(rows[1]!.getAttribute('aria-pressed')).toBe('true');
        expect(key('files').getAttribute('aria-pressed')).toBe('true');
        key('terminal').click();
        await settle();
        expect(rows[1]!.getAttribute('aria-pressed')).toBe('false');
        expect(rows[2]!.getAttribute('aria-pressed')).toBe('true');
        button('edit-take-out')!.click();
        await settle();
        expect(items('bottom')).toEqual([]);
        expect(document.querySelectorAll('[data-k=edit-key]')).toHaveLength(2);
    });

    test('the list is shown only under a coarse pointer, at a 44px floor', () => {
        const css = readFileSync(resolve(__dirname, 'settings.css'), 'utf8');
        expect(css).toMatch(/\.wp-edit__keys\s*\{[^}]*display:\s*none/);
        expect(css).toMatch(/@media \(pointer: coarse\)\s*\{\s*\.wp-edit__keys\s*\{\s*display:\s*flex/);
        expect(css).toMatch(/\[data-k='edit-key'\]\s*\{[^}]*min-height:\s*var\(--oc-tap\)/);
    });

    test('a pressed key is selected and offers move to the other bar and take out of its own', async () => {
        await show();
        key('notes').click();
        await settle();
        expect(key('notes').getAttribute('aria-pressed')).toBe('true');
        expect(button('edit-move')?.textContent?.trim()).toBe('move to bottom bar');
        expect(button('edit-take-out')?.textContent?.trim()).toBe('take out of right bar');
        key('notes').click();
        await settle();
        expect(button('edit-move')).toBeNull();
    });

    test('move to the other bar saves both rails as ONE write and toasts saved with an undo', async () => {
        await show();
        key('notes').click();
        await settle();
        button('edit-move')!.click();
        await settle();
        expect(writes).toEqual([[SIDE, BOTTOM]]);
        expect(items('side')).toEqual(['core.files']);
        expect(items('bottom')).toEqual(['core.shell', 'core.notes']);
        expect(lastToast()['title']).toBe('moved notes to the bottom bar');
        expect(typeof lastToast()['on_action']).toBe('function');
        expect(button('edit-move')).toBeNull();
    });

    test('focus follows the press: onto the moved key in its new bar, onto the hint after a take out', async () => {
        await show();
        key('notes').click();
        await settle();
        button('edit-move')!.click();
        await settle();
        expect(document.activeElement).toBe(document.querySelector('.wp-mockbar--bottom .wp-key[aria-label="notes"]'));
        key('terminal').click();
        await settle();
        button('edit-take-out')!.click();
        await settle();
        expect(document.activeElement).toBe(document.querySelector('.wp-edit__hint'));
    });

    test('focus is not pulled back when the user moved on to another control while the save was in flight', async () => {
        await show();
        const outside = document.createElement('input');
        document.body.append(outside);
        const bridge = g.PreferenceBridge as { writeMany: (entries: { field: string; value: unknown }[]) => Promise<unknown> };
        const original = bridge.writeMany;
        bridge.writeMany = (entries) => { outside.focus(); return original(entries); };
        key('notes').click();
        await settle();
        button('edit-move')!.click();
        await settle();
        expect(document.activeElement).toBe(outside);
        outside.remove();
    });

    test('focus stays on the key when the move did not land', async () => {
        await show();
        verdict = 'conflict';
        key('notes').click();
        await settle();
        button('edit-move')!.click();
        await settle();
        expect(document.activeElement).toBe(document.querySelector('.wp-mockbar--side .wp-key[aria-label="notes"]'));
    });

    test('take out removes only that key from its bar and toasts saved with an undo', async () => {
        await show();
        key('terminal').click();
        await settle();
        button('edit-take-out')!.click();
        await settle();
        expect(writes).toEqual([[BOTTOM]]);
        expect(items('bottom')).toEqual([]);
        expect(items('side')).toEqual(['core.notes', 'core.files']);
        expect(lastToast()['title']).toBe('took terminal out of the bottom bar');
        expect(document.querySelector('.wp-edit__slot')?.textContent).toContain('no widgets in this bar');
    });

    test('a refused save (409) says the bars did not change, the mock shows the server value on its own, and the replay lands', async () => {
        await show();
        verdict = 'conflict';
        key('files').click();
        await settle();
        button('edit-move')!.click();
        await settle();
        expect(lastToast()['title']).toBe('could not save. your bars did not change.');
        expect(lastToast()['alert_severity']).toBe('error');
        expect(toasts.some((toast) => toast['action_label'] === 'undo')).toBe(false);
        await settle();
        expect(items('side')).toEqual(['core.notes', 'core.files']);
        expect(items('bottom')).toEqual(['core.shell']);
        expect([...document.querySelectorAll('.wp-mockbar--side .wp-key')].map((el) => el.getAttribute('aria-label'))).toEqual(['notes', 'files']);
        expect([...document.querySelectorAll('.wp-mockbar--bottom .wp-key')].map((el) => el.getAttribute('aria-label'))).toEqual(['terminal']);
        verdict = 'committed';
        key('files').click();
        await settle();
        button('edit-move')!.click();
        await settle();
        expect(lastToast()['title']).toBe('moved files to the bottom bar');
        expect(items('bottom')).toEqual(['core.shell', 'core.files']);
    });

    test('a save that never settles says not confirmed, frees the queue, and a late landing never turns it into saved', async () => {
        vi.useFakeTimers();
        await show();
        verdict = 'hang';
        key('notes').click();
        await settle();
        button('edit-take-out')!.click();
        await vi.advanceTimersByTimeAsync(SAVE_WAIT_MS + 10);
        await settle();
        expect(lastToast()['title']).toBe('the save has not been confirmed yet. your bars may not have changed.');
        const count = toasts.length;
        emit(SIDE, 'committed');
        await settle();
        expect(toasts).toHaveLength(count);
        verdict = 'committed';
        key('files').click();
        await settle();
        button('edit-take-out')!.click();
        await settle();
        expect(lastToast()['title']).toBe('took files out of the right bar');
    });

    test('the status line is mounted empty and filled on a pick, and the bars are named groups, not navigation', async () => {
        await show();
        const status = document.querySelector('.wp-edit__picked')!;
        expect(status.getAttribute('role')).toBe('status');
        expect(status.textContent).toBe('');
        key('files').click();
        await settle();
        expect(document.querySelector('.wp-edit__picked')).toBe(status);
        expect(status.textContent).toBe('files selected');
        expect(document.querySelectorAll('nav')).toHaveLength(0);
        expect(document.querySelector('.wp-mockbar--side')?.getAttribute('role')).toBe('group');
    });

    test('there is no pointer drag: dragging a key between the bars writes nothing, and no key is draggable', async () => {
        await show();
        const from = key('notes');
        const to = document.querySelector('.wp-mockbar--bottom')!;
        from.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true, clientX: 10, clientY: 10 }));
        to.dispatchEvent(new PointerEvent('pointermove', { bubbles: true, clientX: 300, clientY: 300 }));
        to.dispatchEvent(new PointerEvent('pointerup', { bubbles: true, clientX: 300, clientY: 300 }));
        from.dispatchEvent(new Event('dragstart', { bubbles: true }));
        await settle();
        expect(writes).toEqual([]);
        expect(document.querySelector('[draggable="true"]')).toBeNull();
        const source = readFileSync(resolve(__dirname, 'BarsEditor.svelte'), 'utf8');
        expect(source).not.toMatch(/import[^;]*(drag|pointer)/i);
    });

    test('a hidden bar is not drawn and its caption says to turn it on under show', async () => {
        shared['widget_bars'] = { v: 1, bottom: { show: false } };
        widgetBars.reload();
        await show();
        expect(document.querySelector('.wp-mockbar--bottom')).toBeNull();
        expect(document.querySelectorAll('[data-k=edit-key][data-edge=bottom]')).toHaveLength(0);
        expect(document.querySelector('li[data-edge=bottom]')?.textContent).toBe('the bottom bar is hidden, turn it on under show');
    });

    test('a key that leaves its bar elsewhere clears the selection', async () => {
        await show();
        key('notes').click();
        await settle();
        shared[SIDE] = { v: 2, sections: [{ items: [{ widget: 'core.files' }] }] };
        railStores.side.reload();
        await settle();
        expect(button('edit-move')).toBeNull();
    });
});
