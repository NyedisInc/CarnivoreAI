/** @vitest-environment jsdom */
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { afterEach, describe, expect, test } from 'vitest';
import { mount, unmount } from 'svelte';

import KindMark from './KindMark.svelte';
import { createI18n } from '../../../../client/js/i18n/runtime.js';

const i18n = createI18n({ locale: 'en' }) as {
    t(key: string, params?: Record<string, unknown> | null): string;
};
const t = (key: string, params?: Record<string, unknown> | null) => i18n.t(key, params);

const KINDS = ['mod', 'skill', 'theme', 'plugin', 'loadout'] as const;
const GLYPH: Record<(typeof KINDS)[number], string> = {
    mod: 'mod',
    skill: 'skill',
    theme: 'palette',
    plugin: 'plug',
    loadout: 'pack',
};
const SIZES = ['sm', 'md', 'lg'] as const;

const TOKENS: Record<string, string> = {
    '--oc-kind-mod': 'rgb(1, 0, 0)',
    '--oc-kind-skill': 'rgb(2, 0, 0)',
    '--oc-kind-theme': 'rgb(3, 0, 0)',
    '--oc-kind-plugin': 'rgb(4, 0, 0)',
    '--oc-kind-ink': 'rgb(6, 0, 0)',
    '--oc-orange': 'rgb(7, 0, 0)',
    '--oc-line-rule': 'rgb(8, 0, 0)',
    '--oc-text-secondary': 'rgb(9, 0, 0)',
};

let handle: Record<string, unknown> | null = null;
let styleEl: HTMLStyleElement | null = null;

function injectOwnCss(): void {
    const source = readFileSync(join(process.cwd(), 'src/lib/catalog/KindMark.svelte'), 'utf8');
    const css = /<style>([\s\S]*?)<\/style>/.exec(source)?.[1] ?? '';
    const resolved = css.replace(/var\((--[a-z-]+)\)/g, (_all, name: string) => TOKENS[name] ?? 'rgb(0, 0, 0)');
    styleEl = document.createElement('style');
    styleEl.textContent = resolved;
    document.head.appendChild(styleEl);
}

function render(kind: string, size: 'sm' | 'md' | 'lg'): HTMLElement {
    const host = document.createElement('div');
    document.body.appendChild(host);
    handle = mount(KindMark, { target: host, props: { kind, size, t } });
    return host;
}

afterEach(() => {
    if (handle) unmount(handle);
    handle = null;
    styleEl?.remove();
    styleEl = null;
    document.body.innerHTML = '';
});

describe('KindMark', () => {
    test.each(KINDS.flatMap((kind) => SIZES.map((size) => [kind, size] as const)))(
        '%s at %s renders one tile with its glyph, role and word',
        (kind, size) => {
            const host = render(kind, size);
            const marks = host.querySelectorAll('span.kind-mark');
            expect(marks).toHaveLength(1);
            const mark = marks[0]!;
            expect(mark.classList.contains(`kind-mark--${kind}`)).toBe(true);
            expect(mark.classList.contains(`kind-mark--${size}`)).toBe(true);
            expect(mark.getAttribute('role')).toBe('img');
            expect(mark.getAttribute('aria-label')).toBe(t(`catalog.kind.${kind}`));
            expect(mark.querySelector('svg')?.getAttribute('data-icon')).toBe(GLYPH[kind]);
        },
    );

    test('mod, skill, theme and plugin paint filled colour tiles (themes are no longer black), distinct from the accent', () => {
        injectOwnCss();
        const fills = new Map<string, string>();
        for (const kind of ['mod', 'skill', 'theme', 'plugin']) {
            const mark = render(kind, 'md').querySelector('span.kind-mark') as HTMLElement;
            fills.set(kind, getComputedStyle(mark).backgroundColor);
            unmount(handle as Record<string, unknown>);
            handle = null;
        }
        const accent = 'rgb(7, 0, 0)';
        expect(fills.get('mod')).toBe('rgb(1, 0, 0)');
        expect(fills.get('skill')).toBe('rgb(2, 0, 0)');
        expect(fills.get('theme')).toBe('rgb(3, 0, 0)');
        expect(fills.get('plugin')).toBe('rgb(4, 0, 0)');
        expect(new Set([...fills.values(), accent]).size).toBe(5);
    });

    test('an unknown kind draws the neutral tile, not a coloured one', () => {
        const mark = render('gizmo', 'md').querySelector('span.kind-mark') as HTMLElement;
        expect(mark.className).toContain('kind-mark--gizmo');
        expect(mark.getAttribute('aria-label')).toBe('gizmo');
    });
});
