/** @vitest-environment jsdom */
import { afterEach, describe, expect, test } from 'vitest';
import { createRawSnippet } from 'svelte';

import IconButton from './IconButton.svelte';
import IconButtonBind from './IconButtonBind.fixture.svelte';
import { buttonAttrs } from './classes';
import { cleanup, sheet, show } from './test-helpers';

afterEach(cleanup);

const button = (props: Record<string, unknown>): HTMLButtonElement =>
    show(IconButton, { label: 'close', icon: 'close', ...props }).querySelector('button')!;

describe('IconButton', () => {
    test('the label is the accessible name and the tooltip; the base marker and the icon size are written', () => {
        const el = button({});
        expect(el.getAttribute('aria-label')).toBe('close');
        expect(el.title).toBe('close');
        expect(el.dataset.btn).toBe('secondary');
        expect(el.dataset.size).toBe('icon');
        expect(el.getAttribute('class')).toBeNull();
        expect(el.type).toBe('button');
        expect(el.querySelector('svg')?.getAttribute('aria-hidden')).toBe('true');
    });

    test('a tooltip is the title while the label stays the accessible name; without one the label is both', () => {
        const el = button({ tooltip: 'close (esc)' });
        expect(el.getAttribute('aria-label')).toBe('close');
        expect(el.title).toBe('close (esc)');
        expect(button({}).title).toBe('close');
    });

    test('the variants map onto the one button recipe', () => {
        expect(button({ variant: 'quiet' }).dataset).toMatchObject({ btn: 'quiet', size: 'icon' });
        expect(button({ variant: 'quiet' }).hasAttribute('data-tone')).toBe(false);
        expect(button({ variant: 'close' }).dataset).toMatchObject({ btn: 'quiet', tone: 'close' });
        expect(button({ variant: 'float' }).dataset).toMatchObject({ btn: 'quiet', tone: 'float' });
    });

    test('pressed makes it a toggle; absent leaves it a plain action', () => {
        expect(button({}).hasAttribute('aria-pressed')).toBe(false);
        expect(button({ pressed: false }).getAttribute('aria-pressed')).toBe('false');
        expect(button({ pressed: true }).getAttribute('aria-pressed')).toBe('true');
    });

    test('a click reaches the caller, a disabled one does not, extra attributes pass through', () => {
        let clicks = 0;
        const el = button({ onclick: () => clicks++, 'aria-expanded': true, 'data-probe': '1' });
        el.click();
        expect(clicks).toBe(1);
        expect(el.getAttribute('aria-expanded')).toBe('true');
        expect(el.dataset.probe).toBe('1');
        const off = button({ onclick: () => clicks++, disabled: true });
        off.click();
        expect(clicks).toBe(1);
        expect(off.disabled).toBe(true);
    });

    test('children replace the icon', () => {
        const el = button({ icon: undefined, children: createRawSnippet(() => ({ render: () => '<b data-glyph>x</b>' })) });
        expect(el.querySelector('[data-glyph]')).not.toBeNull();
        expect(el.querySelector('svg')).toBeNull();
    });

    test('a bound element is the rendered button, for a caller that anchors a popup to it', () => {
        const seen: { el: HTMLElement | null } = { el: null };
        const root = show(IconButtonBind, { seen });
        expect(seen.el).not.toBeNull();
        expect(seen.el).toBe(root.querySelector('button'));
    });

    test('the markup is what the class API writes', () => {
        expect(buttonAttrs('quiet', 'icon')).toEqual({ 'data-btn': 'quiet', 'data-size': 'icon' });
    });
});

describe('icon-button.css', () => {
    const rules = sheet('icon-button.css');
    const find = (needle: string) => rules.filter((r) => r.selector.includes(needle));

    test('the square is the ibtn size token, the phone gets the tap target, the widget head keeps its own', () => {
        expect(find("[data-btn][data-size='icon']")[0]!.decls.width).toBe('var(--oc-ibtn-size, var(--oc-control-h-xs))');
        const phone = rules.filter((r) => r.within.some((w) => w.includes('max-width: 1023px')));
        expect(phone.map((r) => r.decls.width)).toContain('var(--oc-tap)');
        expect(phone.some((r) => r.selector.includes('[data-widget-head]'))).toBe(true);
    });

    test('the square does not clip: a corner badge on a key stays whole (the label clip is for text buttons)', () => {
        expect(find("[data-btn][data-size='icon']")[0]!.decls.overflow).toBe('visible');
    });

    test('quiet draws a transparent edge and the close tone turns coral only on hover', () => {
        const quiet = rules.find((r) => r.selector === ":where([data-btn='quiet'][data-size='icon'])")!;
        expect(quiet.decls['--_btn-edge']).toBe('transparent');
        expect(quiet.decls['--_btn-edge-hover']).toBe('transparent');
        const close = find("data-tone='close'")[0]!;
        expect(close.decls['--_btn-ink-hover']).toBe('var(--oc-coral)');
        expect(close.decls['--_btn-ink']).toBeUndefined();
    });

    test('the sheet carries no literal color and no hidden literal in a private property', () => {
        const text = rules.map((r) => Object.values(r.decls).join(' ')).join(' ');
        expect(text).not.toMatch(/#[0-9a-f]{3,8}\b|rgb\(|\d+px/i);
    });
});
