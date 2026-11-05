/** @vitest-environment jsdom */
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { afterEach, beforeEach, describe, expect, test } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

import BarsSettings from './BarsSettings.svelte';
import { widgetBars } from '../../widget-bars/bar-settings.svelte';
import { t } from '../../i18n/index.svelte';
import { stubResizeObserver } from './mock-test-support';

type Write = { field: string; value: unknown };
const g = globalThis as Record<string, unknown>;
let writes: Write[];
let shared: Record<string, unknown>;
let toasts: Record<string, unknown>[];
let mounted: Record<string, unknown> | null = null;

beforeEach(() => {
    stubResizeObserver();
    writes = [];
    shared = {};
    toasts = [];
    g.PreferenceBridge = {
        read: (field: string) => shared[field] ?? null,
        write: async (field: string, value: unknown) => { writes.push({ field, value }); shared[field] = value; return { status: 'committed' }; },
        writeMany: async () => ({ status: 'committed' }),
        follow: () => () => {},
    };
    g.ToastManager = { add: (toast: Record<string, unknown>) => toasts.push(toast), dismiss: () => {} };
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
    widgetBars.reload();
    mounted = mount(BarsSettings, { target: document.body, props: { t } });
    await settle();
}
const radio = (name: string): HTMLElement => document.querySelector<HTMLElement>(`[role=radio][aria-label="${name}"]`)!;

describe('BarsSettings', () => {
    test('a size pick writes only that leaf, and undo writes it away so the default is a default again', async () => {
        await show();
        radio('right bar size detailed, 68px').click();
        await settle();
        expect(writes.at(-1)).toEqual({ field: 'widget_bars', value: { v: 1, side: { size: 'detailed' } } });
        const undo = toasts.at(-1)!['on_action'] as () => void;
        undo();
        await settle();
        expect(writes.at(-1)).toEqual({ field: 'widget_bars', value: null });
    });

    test('bottom only writes the right bar hidden and nothing for the bottom bar; one at a time writes together', async () => {
        await show();
        radio('show bottom only').click();
        await settle();
        expect(writes).toEqual([{ field: 'widget_bars', value: { v: 1, side: { show: false } } }]);
        radio('bars one at a time').click();
        await settle();
        expect(writes.at(-1)?.value).toEqual({ v: 1, side: { show: false }, together: 'one' });
    });

    test('saved settings show before any press, and a hidden bar dims its size strip', async () => {
        shared['widget_bars'] = { v: 1, bottom: { size: 'compact', show: false } };
        await show();
        expect(radio('bottom bar size compact, 20px').getAttribute('aria-checked')).toBe('true');
        expect(document.querySelectorAll('.wp-strip--dim')).toHaveLength(1);
        expect(radio('show right only').getAttribute('aria-checked')).toBe('true');
    });

    test('reset is disabled at the defaults and enabled once something is saved', async () => {
        await show();
        const reset = (): HTMLButtonElement => document.querySelector<HTMLButtonElement>('[data-k=settings-reset]')!;
        expect(reset().disabled).toBe(true);
        radio('right bar mode auto-hide').click();
        await settle();
        expect(reset().disabled).toBe(false);
    });

    test('an arrow key moves the pick and applies it', async () => {
        await show();
        radio('right bar size cozy, 36px').dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }));
        await settle();
        expect(writes.at(-1)?.value).toEqual({ v: 1, side: { size: 'detailed' } });
    });

    test('the stylesheet names no literal color, so every shipped theme paints the tab', () => {
        const css = readFileSync(resolve(__dirname, 'settings.css'), 'utf8').replace(/\/\*[\s\S]*?\*\//g, '');
        expect(css).not.toMatch(/#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(|oklch\(/);
    });

    test('the default tag and the figure are separate elements, spaced by the layout and not by a text space', async () => {
        await show();
        const figure = radio('right bar size cozy, 36px').querySelector('.wp-pic__figure')!;
        const tag = figure.querySelector('.wp-pic__default')!;
        const note = figure.querySelector('.wp-pic__note')!;
        expect(tag.textContent).toBe('default');
        expect(note.textContent).toBe('36px');
        expect(tag.nextElementSibling).toBe(note);
        const css = readFileSync(resolve(__dirname, 'settings.css'), 'utf8');
        expect(css).toMatch(/\.wp-pic__figure\s*\{[^}]*display:\s*flex[^}]*gap:[^;]*var\(--oc-space-/);
    });

    test('the card hints wrap at phone width through a rule scoped to the tab, leaving the shared class alone', () => {
        const css = readFileSync(resolve(__dirname, 'settings.css'), 'utf8');
        expect(css).toMatch(/\.wp-settings\s+\.oc-card__meta\s*\{[^}]*white-space:\s*normal/);
        expect(readFileSync(resolve(__dirname, '../../base/card.css'), 'utf8')).toMatch(/\.oc-card__meta\s*\{[^}]*white-space:\s*nowrap/);
    });
});
