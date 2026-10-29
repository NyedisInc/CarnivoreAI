/** @vitest-environment jsdom */
import { afterEach, describe, expect, test } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

import ColorSwatches from './ColorSwatches.svelte';
import { installPopoverPolyfill } from '../popover-jsdom-polyfill';
import { createI18n } from '../../../../client/js/i18n/runtime.js';

const i18n = createI18n();
const t = (key: string, params?: Record<string, unknown> | null) => i18n.t(key, params);
installPopoverPolyfill();

let app: unknown = null;
let picks: Array<string | null> = [];

function render(value: string | null, disabled = false, opened = true): void {
    picks = [];
    app = mount(ColorSwatches, {
        target: document.body,
        props: { value, t, disabled, onPick: (hex: string | null) => picks.push(hex) },
    });
    flushSync();
    if (opened) openIt();
}

function openIt(): void {
    (document.querySelector('[data-ledger="color-chip"]') as HTMLButtonElement).click();
    flushSync();
}

afterEach(() => {
    if (app) unmount(app as never);
    app = null;
    document.body.innerHTML = '';
});

const cells = () => [...document.querySelectorAll<HTMLButtonElement>('.ledger-tcell')];
const hexField = () => document.querySelector<HTMLInputElement>('[data-ledger="color-hex"]') as HTMLInputElement;
const readout = () => document.querySelector('.ledger-tpick__readout')?.textContent;

describe('the terminal colour picker', () => {
    test('closed it is one chip; the chip opens the popup with the whole grid', () => {
        render('#00d7d7', false, false);
        expect(cells()).toHaveLength(0);
        expect(document.querySelector('[data-ledger="color-chip"]')?.textContent?.trim()).toBe('#00d7d7');
        openIt();
        expect(document.querySelector('.ledger-tpick__panel')).not.toBeNull();
        expect(cells()).toHaveLength(249);
        expect(cells().filter((c) => c.tabIndex === 0)).toHaveLength(1);
        expect(cells().find((c) => c.dataset.idx === '44')?.getAttribute('style')).toContain('#00d7d7');
    });

    test('a cell closes the popup and emits; escape closes and returns focus to the chip', () => {
        render('#123456');
        (cells().find((c) => c.dataset.idx === '9') as HTMLButtonElement).click();
        flushSync();
        expect(picks).toEqual(['#ff0000']);
        expect(document.querySelector('.ledger-tpick__panel')).toBeNull();
        openIt();
        document.querySelector('.ledger-tpick__panel')?.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
        flushSync();
        expect(document.querySelector('.ledger-tpick__panel')).toBeNull();
        expect(picks).toEqual(['#ff0000']);
        expect(document.activeElement).toBe(document.querySelector('[data-ledger="color-chip"]'));
    });

    test('a pointer outside closes the popup and keeps the choice', () => {
        render('#123456');
        document.body.dispatchEvent(new Event('pointerdown', { bubbles: true }));
        flushSync();
        expect(document.querySelector('.ledger-tpick__panel')).toBeNull();
        expect(picks).toEqual([]);
    });

    test('clicking a cell emits its lowercase #rrggbb and none emits null', () => {
        render('#123456');
        (cells().find((c) => c.dataset.idx === '9') as HTMLButtonElement).click();
        openIt();
        (document.querySelector('[data-ledger="color-none"]') as HTMLButtonElement).click();
        expect(picks).toEqual(['#ff0000', null]);
    });

    test('the chosen colour marks its cell and the readout names it', () => {
        render('#00d7d7');
        const on = cells().filter((c) => c.getAttribute('aria-pressed') === 'true');
        expect(on.map((c) => c.dataset.idx)).toEqual(['44']);
        expect(readout()).toBe('idx 044  #00d7d7');
    });

    test('a stored colour equal to a dropped duplicate selects its surviving cell', () => {
        render('#ff0000');
        expect(cells().some((c) => c.dataset.idx === '196')).toBe(false);
        const on = cells().filter((c) => c.getAttribute('aria-pressed') === 'true');
        expect(on.map((c) => c.dataset.idx)).toEqual(['9']);
        expect(readout()).toBe('idx 009  #ff0000');
    });

    test('hovering a cell updates the readout', () => {
        render(null);
        cells().find((c) => c.dataset.idx === '21')?.dispatchEvent(new MouseEvent('mouseenter'));
        flushSync();
        expect(readout()).toBe('idx 021  #0000ff');
    });

    test('hex entry emits only a whole valid colour, lowercased, and flags the rest', () => {
        render(null);
        const type = (v: string) => {
            hexField().value = v;
            hexField().dispatchEvent(new Event('input', { bubbles: true }));
            flushSync();
        };
        type('12ab');
        expect(picks).toEqual([]);
        expect(hexField().getAttribute('aria-invalid')).toBe('true');
        type('12ABEF');
        expect(picks).toEqual(['#12abef']);
        type('#00D7D7');
        expect(picks[picks.length - 1]).toBe('#00d7d7');
    });

    test('arrow keys move the roving tab stop', () => {
        render('#000000');
        const first = cells()[0] as HTMLButtonElement;
        first.focus();
        first.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true }));
        flushSync();
        expect(cells()[1]?.tabIndex).toBe(0);
        expect(first.tabIndex).toBe(-1);
    });

    test('a colour near a status light hue gets a note and is still stored', () => {
        render('#ff0000');
        expect(document.querySelector('.ledger-tpick__note')).not.toBeNull();
    });
});
