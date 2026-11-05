/** @vitest-environment jsdom */
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

import TryIt from './TryIt.svelte';
import { railStores } from '../../session-rail/rail-store.svelte';
import { widgetBars } from '../../widget-bars/bar-settings.svelte';
import { t } from '../../i18n/index.svelte';
import { stubResizeObserver } from './mock-test-support';
import { PANEL_PX } from './try-scene.svelte';

const g = globalThis as Record<string, unknown>;
let shared: Record<string, unknown>;
let mounted: Record<string, unknown> | null = null;

beforeEach(() => {
    stubResizeObserver();
    shared = {
        session_rail: { v: 2, sections: [{ items: [{ widget: 'core.notes' }, { widget: 'core.files' }] }] },
        session_rail_bottom: { v: 2, sections: [{ items: [{ widget: 'core.shell' }] }] },
        widget_bars: { v: 1, side: { mode: 'autohide' }, bottom: { mode: 'autohide' } },
    };
    g.PreferenceBridge = { read: (field: string) => shared[field] ?? null, write: async () => ({ status: 'committed' }), writeMany: async () => ({ status: 'committed' }), follow: () => () => {} };
    g.ToastManager = { add: () => {}, dismiss: () => {} };
    railStores.side.reload();
    railStores.bottom.reload();
    widgetBars.reload();
});
afterEach(() => {
    if (mounted) unmount(mounted);
    mounted = null;
    document.body.innerHTML = '';
});

async function settle(): Promise<void> {
    for (let i = 0; i < 6; i += 1) await Promise.resolve();
    await tick();
    flushSync();
}
async function show(): Promise<void> {
    mounted = mount(TryIt, { target: document.body, props: { t } });
    await settle();
}
const layer = (edge: string): HTMLElement => document.querySelector<HTMLElement>(`.wp-try__layer[data-edge=${edge}]`)!;
const key = (name: string): HTMLButtonElement => document.querySelector<HTMLButtonElement>(`.wp-key[aria-label^="${name}"]`)!;
const pinEdge = (edge: string): HTMLElement => document.querySelector<HTMLElement>(`[data-try-pin=${edge}]`)!;
const pointer = (el: Element, type: string, x: number): void => void el.dispatchEvent(new PointerEvent(type, { bubbles: true, button: 0, clientX: x, clientY: 0, pointerId: 1 }));
const click = (edge: string): void => { pointer(pinEdge(edge), 'pointerdown', 200); pointer(pinEdge(edge), 'pointerup', 200); };
async function openNotes(): Promise<void> {
    layer('side').dispatchEvent(new PointerEvent('pointerenter'));
    await settle();
    key('notes').click();
    await settle();
}

describe('TryIt', () => {
    test('at rest each bar is F1\'s handle, with no strip drawn and no panel', async () => {
        await show();
        expect(layer('side').dataset['state']).toBe('handle');
        expect(layer('bottom').dataset['state']).toBe('handle');
        expect(layer('side').querySelector('[data-bar-handle]')).not.toBeNull();
        expect(document.querySelector('.wp-mockbar')).toBeNull();
        expect(document.querySelector('.wp-try__panel')).toBeNull();
    });

    test('the pointer on a bar\'s edge peeks it out with its keys and F1\'s pin icon; the other bar stays a handle', async () => {
        await show();
        layer('side').dispatchEvent(new PointerEvent('pointerenter'));
        await settle();
        expect(layer('side').dataset['state']).toBe('peek');
        expect([...layer('side').querySelectorAll('.wp-key')].map((el) => el.getAttribute('aria-label'))).toEqual(['notes', 'files']);
        expect(layer('side').querySelector('[data-bar-pin]')).not.toBeNull();
        expect(layer('bottom').dataset['state']).toBe('handle');
    });

    test('a key press opens a sample panel with the widget\'s title and the one sample line, and nothing else', async () => {
        await show();
        await openNotes();
        expect(layer('side').dataset['state']).toBe('held');
        expect(key('notes').getAttribute('aria-expanded')).toBe('true');
        const panel = document.querySelector('.wp-try__panel')!;
        expect(panel.querySelector('.wp-try__panel-title')?.textContent).toBe('notes');
        expect(panel.querySelector('.wp-try__panel-note')?.textContent).toBe('sample panel, nothing here is real');
        expect(panel.querySelectorAll('.wp-try__panel-body > *')).toHaveLength(2);
    });

    test('pressing the panel\'s thin edge pins it (the accent line, the pinned name), pressing again lets go', async () => {
        await show();
        await openNotes();
        expect(pinEdge('side').getAttribute('aria-label')).toBe('drag to resize, click to pin');
        click('side');
        await settle();
        expect(pinEdge('side').classList.contains('wp-try__pin--on')).toBe(true);
        expect(pinEdge('side').getAttribute('aria-label')).toBe('pinned on build agent, click to unpin');
        click('side');
        await settle();
        expect(pinEdge('side').classList.contains('wp-try__pin--on')).toBe(false);
    });

    test('dragging the edge resizes the panel inside the scene and does not pin it; the keys do the same', async () => {
        await show();
        await openNotes();
        pointer(pinEdge('side'), 'pointerdown', 300);
        pointer(pinEdge('side'), 'pointermove', 200);
        pointer(pinEdge('side'), 'pointerup', 200);
        await settle();
        expect(document.querySelector<HTMLElement>('.wp-try__panel')!.style.getPropertyValue('--panel-px')).toBe(`${PANEL_PX.side.initial + 100}px`);
        expect(pinEdge('side').classList.contains('wp-try__pin--on')).toBe(false);
        pinEdge('side').dispatchEvent(new KeyboardEvent('keydown', { key: 'Home', bubbles: true }));
        await settle();
        expect(document.querySelector<HTMLElement>('.wp-try__panel')!.style.getPropertyValue('--panel-px')).toBe(`${PANEL_PX.side.initial}px`);
        pinEdge('side').dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
        await settle();
        expect(pinEdge('side').classList.contains('wp-try__pin--on')).toBe(true);
    });

    test('switching agent puts F1\'s badge, with the pinned agent\'s letter, on the key of a panel pinned on the other one', async () => {
        await show();
        await openNotes();
        click('side');
        await settle();
        expect(key('notes').querySelector('[data-pinned-key-badge]')).toBeNull();
        (document.querySelector('[data-k=try-switch]') as HTMLElement).click();
        await settle();
        expect(document.querySelector('.wp-try__active')?.textContent).toBe('active agent: review agent');
        expect(key('notes').querySelector('[data-pinned-key-badge]')?.textContent).toBe('B');
        expect(key('notes').getAttribute('aria-label')).toBe('notes, pinned on build agent');
        click('side');
        await settle();
        click('side');
        await settle();
        (document.querySelector('[data-k=try-switch]') as HTMLElement).click();
        await settle();
        expect(key('notes').querySelector('[data-pinned-key-badge]')?.textContent).toBe('R');
    });

    test('F1\'s handle, pin and badge are mounted, not redrawn here, and the scene stores nothing', () => {
        const tryIt = readFileSync(resolve(__dirname, 'TryIt.svelte'), 'utf8');
        const bar = readFileSync(resolve(__dirname, 'MockBar.svelte'), 'utf8');
        expect(tryIt).toMatch(/import ZoneHandle from '\.\.\/\.\.\/zone-shell\/ZoneHandle\.svelte'/);
        expect(tryIt).not.toMatch(/<BarHandle/);
        expect(tryIt).toMatch(/import BarPin from '\.\.\/\.\.\/widget-bars\/BarPin\.svelte'/);
        expect(bar).toMatch(/import PinnedKeyBadge from '\.\.\/\.\.\/widget-bars\/PinnedKeyBadge\.svelte'/);
    });

    test('the scene stores nothing: peek, open, pin, resize and switch agent write no preference and no browser storage', async () => {
        const bridgeWrites: string[] = [];
        const bridge = g.PreferenceBridge as Record<string, unknown>;
        g.PreferenceBridge = {
            ...bridge,
            write: async (field: string) => { bridgeWrites.push(field); return { status: 'committed' }; },
            writeMany: async (entries: { field: string }[]) => { bridgeWrites.push(...entries.map((entry) => entry.field)); return { status: 'committed' }; },
        };
        const stored: string[] = [];
        const setItem = vi.spyOn(Storage.prototype, 'setItem').mockImplementation((name: string) => void stored.push(name));
        try {
            await show();
            await openNotes();
            click('side');
            await settle();
            pointer(pinEdge('side'), 'pointerdown', 300);
            pointer(pinEdge('side'), 'pointermove', 200);
            pointer(pinEdge('side'), 'pointerup', 200);
            pinEdge('side').dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowLeft', bubbles: true }));
            (document.querySelector('[data-k=try-switch]') as HTMLElement).click();
            key('notes').click();
            await settle();
            expect(bridgeWrites).toEqual([]);
            expect(stored).toEqual([]);
        } finally {
            setItem.mockRestore();
        }
    });
});
