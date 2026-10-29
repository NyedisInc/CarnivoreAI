/** @vitest-environment jsdom */
import { afterEach, describe, expect, test } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

import IconPicker from './IconPicker.svelte';
import IconMark from './IconMark.svelte';
import IconPickerDemo from '../../style-guide/specimens/IconPickerDemo.svelte';
import { PICKABLE_ICONS } from './icon-model';
import { createI18n } from '../../../../client/js/i18n/runtime.js';
import { PSEUDO_LOCALE } from '../../../../client/js/i18n/pseudo.js';
import type { Translate } from '../sessions/types';

const en = createI18n({ locale: 'en' }) as { t: Translate };
const t: Translate = (key, params) => en.t(key, params);
const pseudo = createI18n({ locale: PSEUDO_LOCALE }) as { t: Translate };
const tPseudo: Translate = (key, params) => pseudo.t(key, params);

let mounted: Record<string, unknown> | null = null;

afterEach(() => {
    if (mounted) unmount(mounted);
    mounted = null;
    document.body.innerHTML = '';
});

async function show(
    component: unknown,
    props: Record<string, unknown>,
    parentColor?: string,
): Promise<HTMLElement> {
    const target = document.createElement('div');
    if (parentColor) target.style.color = parentColor;
    document.body.append(target);
    mounted = mount(component as never, { target, props });
    await tick();
    flushSync();
    return target;
}

async function press(el: Element, key: string): Promise<void> {
    el.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true }));
    await tick();
    flushSync();
}

const grid = (root: HTMLElement): HTMLElement => root.querySelector('[role="listbox"]') as HTMLElement;
const activeCell = (root: HTMLElement): HTMLElement =>
    document.getElementById(grid(root).getAttribute('aria-activedescendant') ?? '') as HTMLElement;

describe('the picker', () => {
    test('offers "no icon" first, then every registry icon', async () => {
        const root = await show(IconPicker, { value: null, onChange: () => {}, t });
        const cells = [...root.querySelectorAll('[role="option"]')];
        expect(cells).toHaveLength(PICKABLE_ICONS.length + 1);
        expect(cells[0]!.textContent).toContain('no icon');
        expect(cells[1]!.querySelector('[data-icon-id]')?.getAttribute('data-icon-id')).toBe(PICKABLE_ICONS[0]!.id);
    });

    test('marks the current value selected, and starts the keyboard on it', async () => {
        const root = await show(IconPicker, { value: 'users', onChange: () => {}, t });
        const selected = root.querySelectorAll('[aria-selected="true"]');
        expect(selected).toHaveLength(1);
        expect(selected[0]!.querySelector('[data-icon-id]')?.getAttribute('data-icon-id')).toBe('users');
        expect(activeCell(root)).toBe(selected[0]!);
    });

    test('an unknown stored id selects nothing and does not throw', async () => {
        const root = await show(IconPicker, { value: 'from-the-future', onChange: () => {}, t });
        expect(root.querySelectorAll('[aria-selected="true"]')).toHaveLength(0);
    });

    test('arrows move the active cell by one and by a row, Enter reports the id', async () => {
        const picked: Array<string | null> = [];
        const root = await show(IconPicker, { value: null, onChange: (id: string | null) => picked.push(id), t });
        const g = grid(root);
        expect(activeCell(root).textContent).toContain('no icon');
        await press(g, 'ArrowRight');
        await press(g, 'ArrowDown');
        expect(activeCell(root).querySelector('[data-icon-id]')?.getAttribute('data-icon-id'))
            .toBe(PICKABLE_ICONS[8]!.id);
        await press(g, 'Enter');
        expect(picked).toEqual([PICKABLE_ICONS[8]!.id]);
        await press(g, 'Home');
        await press(g, ' ');
        expect(picked).toEqual([PICKABLE_ICONS[8]!.id, null]);
    });

    test('End reaches the last icon, Escape calls onCancel', async () => {
        let cancelled = 0;
        const root = await show(IconPicker, { value: null, onChange: () => {}, onCancel: () => { cancelled += 1; }, t });
        await press(grid(root), 'End');
        expect(activeCell(root).querySelector('[data-icon-id]')?.getAttribute('data-icon-id'))
            .toBe(PICKABLE_ICONS[PICKABLE_ICONS.length - 1]!.id);
        await press(grid(root), 'Escape');
        expect(cancelled).toBe(1);
    });

    test('a click reports the id', async () => {
        const picked: Array<string | null> = [];
        const root = await show(IconPicker, { value: null, onChange: (id: string | null) => picked.push(id), t });
        (root.querySelector('[data-icon-id="globe"]')?.closest('[role="option"]') as HTMLElement).click();
        expect(picked).toEqual(['globe']);
    });

    test('search narrows the grid, keeps "no icon", and says when nothing matches', async () => {
        const root = await show(IconPicker, { value: null, onChange: () => {}, t });
        const input = root.querySelector('input') as HTMLInputElement;
        input.value = 'team';
        input.dispatchEvent(new Event('input', { bubbles: true }));
        await tick();
        flushSync();
        const ids = [...root.querySelectorAll('[data-icon-id]')].map((el) => el.getAttribute('data-icon-id'));
        expect(ids).toEqual(['users']);
        expect(activeCell(root).querySelector('[data-icon-id]')?.getAttribute('data-icon-id')).toBe('users');
        input.value = 'zzzz';
        input.dispatchEvent(new Event('input', { bubbles: true }));
        await tick();
        flushSync();
        expect(root.querySelectorAll('[role="option"]')).toHaveLength(1);
        expect(root.textContent).toContain('no icons match');
    });

    test('ArrowDown in the search field moves focus into the grid', async () => {
        const root = await show(IconPicker, { value: null, onChange: () => {}, t });
        const input = root.querySelector('input') as HTMLInputElement;
        input.focus();
        await press(input, 'ArrowDown');
        expect(document.activeElement).toBe(grid(root));
    });

    test('has NO colour control and sets no colour on any preview', async () => {
        const root = await show(IconPicker, { value: 'folder', onChange: () => {}, t }, 'rgb(1, 2, 3)');
        expect(root.querySelector('input[type="color"]')).toBeNull();
        expect(root.querySelectorAll('input')).toHaveLength(1);
        for (const el of root.querySelectorAll('[role="listbox"], [role="listbox"] *')) {
            expect((el as HTMLElement).style?.color ?? '').toBe('');
            const stroke = el.getAttribute('stroke');
            if (stroke !== null) expect(stroke).toBe('currentColor');
            const fill = el.getAttribute('fill');
            if (fill !== null) expect(['none', 'currentColor']).toContain(fill);
        }
    });

    test('every word comes from the catalog', async () => {
        const root = await show(IconPicker, { value: null, onChange: () => {}, t: tPseudo });
        const input = root.querySelector('input') as HTMLInputElement;
        expect(input.placeholder).toMatch(/^⟦.*⟧$/);
        expect(root.querySelector('.icp__label')?.textContent).toMatch(/^⟦.*⟧$/);
        for (const sr of root.querySelectorAll('.icp__sr')) expect(sr.textContent).toMatch(/^⟦.*⟧$/);
    });
});

describe('the mark', () => {
    test('renders a known id as the glyph, inheriting the parent colour through currentColor', async () => {
        const root = await show(IconMark, { id: 'folder', size: 12 }, 'rgb(10, 20, 30)');
        const svg = root.querySelector('svg') as SVGElement;
        expect(svg.getAttribute('width')).toBe('12');
        expect(root.querySelector('[data-icon-id="folder"]')?.getAttribute('aria-hidden')).toBe('true');
        const painted = [...svg.querySelectorAll('[stroke], [fill]')];
        expect(painted.length).toBeGreaterThan(0);
        for (const el of painted) {
            const stroke = el.getAttribute('stroke');
            if (stroke !== null) expect(stroke).toBe('currentColor');
        }
        expect(getComputedStyle(svg).color).toBe('rgb(10, 20, 30)');
    });

    test('an unknown or empty id renders nothing at all', async () => {
        for (const id of ['nope', '', null, undefined]) {
            const root = await show(IconMark, { id });
            expect(root.innerHTML.replace(/<!--.*?-->/g, '')).toBe('');
            unmount(mounted as Record<string, unknown>);
            mounted = null;
        }
    });

    test('a label makes it an image with a name', async () => {
        const root = await show(IconMark, { id: 'star', label: 'favorites' });
        const mark = root.querySelector('[data-icon-id="star"]') as HTMLElement;
        expect(mark.getAttribute('role')).toBe('img');
        expect(mark.getAttribute('aria-label')).toBe('favorites');
        expect(mark.hasAttribute('aria-hidden')).toBe(false);
    });
});

describe('the style guide specimen', () => {
    test('a pick redraws the heading mark in the parent colour', async () => {
        const root = await show(IconPickerDemo, { initial: null, tone: '--oc-green', t });
        const heading = root.querySelector('[data-sg-icp-heading]') as HTMLElement;
        expect(heading.querySelector('svg')).toBeNull();
        (root.querySelector('[data-icon-id="bolt"]')?.closest('[role="option"]') as HTMLElement).click();
        await tick();
        flushSync();
        expect(heading.querySelector('[data-icon-id="bolt"] svg')).not.toBeNull();
    });
});
