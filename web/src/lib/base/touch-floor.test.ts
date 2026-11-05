/** @vitest-environment jsdom */
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, test } from 'vitest';

const read = (p: string): string => readFileSync(resolve(process.cwd(), p), 'utf8').replace(/\/\*[\s\S]*?\*\//g, '');
const BASE = read('src/lib/base/elements.css');
const MK2 = read('src/opscenter/cells/task-manager-mk2/mk2-design.css');

function block(css: string, open: number): [string, number] {
    let depth = 0;
    for (let i = open; i < css.length; i++) {
        if (css[i] === '{') depth++;
        if (css[i] === '}' && --depth === 0) return [css.slice(open + 1, i), i + 1];
    }
    throw new Error('unbalanced braces');
}

function coarseFloorSelectors(css: string): string[] {
    const out: string[] = [];
    for (const m of css.matchAll(/@media \(pointer: coarse\)\s*\{/g)) {
        const [body] = block(css, (m.index ?? 0) + m[0].length - 1);
        for (const r of body.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
            if (/min-height\s*:|--_btn-h\s*:\s*var\(--oc-tap\)/.test(r[2])) out.push(r[1].trim());
        }
    }
    return out;
}

const floored = (selectors: string[], el: Element): boolean => selectors.some((s) => el.matches(s));

function button(attrs: Record<string, string>, inside: boolean): HTMLElement {
    const host = document.createElement('div');
    if (inside) host.className = 'mk2-design';
    const b = document.createElement('button');
    b.setAttribute('data-btn', '');
    for (const [k, v] of Object.entries(attrs)) b.setAttribute(k, v);
    host.appendChild(b);
    document.body.appendChild(host);
    return b;
}

const SELECTORS = [...coarseFloorSelectors(BASE), ...coarseFloorSelectors(MK2)];
const VARIANTS = ['', 'secondary', 'confirm', 'danger', 'quiet', 'row'];
const SIZES: Array<string | null> = [null, 'sm'];

describe('the coarse-pointer touch floor lives on the base button', () => {
    test.each(VARIANTS.flatMap((v) => SIZES.map((s) => [v, s] as const)))('data-btn=%j size=%j has the same floor inside and outside .mk2-design', (variant, size) => {
        const attrs: Record<string, string> = { 'data-btn': variant };
        if (size) attrs['data-size'] = size;
        const outside = floored(SELECTORS, button(attrs, false));
        const inside = floored(SELECTORS, button(attrs, true));
        expect(outside).toBe(true);
        expect(inside).toBe(outside);
    });

    test('a button that draws its own box (auto, bare, icon) keeps its own size', () => {
        for (const size of ['auto', 'bare', 'icon']) expect(floored(coarseFloorSelectors(BASE), button({ 'data-size': size }, false))).toBe(false);
    });

    test('Mark II sets no height floor of its own on a base button', () => {
        expect(coarseFloorSelectors(MK2).filter((s) => s.includes('data-btn'))).toEqual([]);
    });

    test('the floor reads the --oc-tap token, never a literal height', () => {
        expect(coarseFloorSelectors(BASE).length).toBeGreaterThan(0);
        expect(BASE).not.toMatch(/@media \(pointer: coarse\)\s*\{[^@]*min-height:\s*\d/);
    });

    test('negative control: a button no coarse rule names is reported as having no floor', () => {
        expect(floored(['[data-never]'], button({}, false))).toBe(false);
    });
});
