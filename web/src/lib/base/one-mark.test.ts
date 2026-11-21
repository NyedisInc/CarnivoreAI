import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';
import { expect, test } from 'vitest';

import { cssRules } from './css-rules';

const SRC = new URL('../../', import.meta.url).pathname;
const MARK_SHEET = 'lib/base/mark.css';
const MARK_CLASS = /\.(?:oc-check__box|oc-radio|oc-option__box|oc-pick__input|acm-box)(?:--[\w-]+)?(?![\w-])/;
const DRAWS = new Set(['width', 'height', 'border', 'border-width', 'border-style', 'border-radius', 'background', 'background-image', 'background-size']);

function walk(dir: string, suffixes: string[]): string[] {
    return readdirSync(dir).flatMap((name) => {
        const path = join(dir, name);
        if (name === 'node_modules' || name === '__goldens__') return [];
        if (statSync(path).isDirectory()) return walk(path, suffixes);
        return suffixes.some((s) => name.endsWith(s)) ? [relative(SRC, path)] : [];
    });
}

function styleOf(text: string, svelte: boolean): string {
    if (!svelte) return text;
    return [...text.matchAll(/<style[^>]*>([\s\S]*?)<\/style>/g)].map((m) => m[1] ?? '').join('\n');
}

function subject(selector: string): string {
    const plain = selector.replace(/:global\(([^()]*)\)/g, '$1').replace(/:(?:not|is|where|has)\((?:[^()]|\([^()]*\))*\)/g, '');
    const parts = plain.trim().split(/\s*[\s>+~]\s*/);
    return parts[parts.length - 1] ?? '';
}

function markCopies(name: string, css: string): string[] {
    return cssRules(css).flatMap((rule) =>
        rule.selector.split(',').flatMap((one) => {
            const subj = subject(one);
            if (!MARK_CLASS.test(subj)) return [];
            if (/::?(?:before|after)/.test(subj)) return [`${name}: ${one.trim()} -> a mark of its own`];
            const drawn = Object.keys(rule.decls).filter((p) => DRAWS.has(p));
            return drawn.length ? [`${name}: ${one.trim()} -> ${drawn.join(', ')}`] : [];
        }),
    );
}

test('the one mark sheet draws every family', () => {
    const mark = readFileSync(join(SRC, MARK_SHEET), 'utf8');
    for (const cls of ['.oc-check__box', '.oc-radio', '.oc-option__box', '.oc-pick__input']) expect(mark).toContain(cls);
    expect(mark).toContain('width: var(--oc-mark)');
});

test('no other sheet or style block draws a check mark', () => {
    const files = walk(SRC, ['.css', '.svelte']).filter((f) => f !== MARK_SHEET);
    expect(files.length).toBeGreaterThan(100);
    const copies = files.flatMap((f) => markCopies(f, styleOf(readFileSync(join(SRC, f), 'utf8'), f.endsWith('.svelte'))));
    expect(copies).toEqual([]);
});

test('negative control: a planted box and a second middle are named, an ink or edge change is not', () => {
    const planted = [
        '.x .oc-check__box { width: 12px; border: 1px solid red; }',
        '[aria-checked=true] .oc-radio::after { content: ""; }',
        '.danger .oc-pick__input { --_mark-ink: var(--oc-coral); border-color: var(--oc-coral); }',
        '.oc-radio-group { width: 10px; }',
        '.acm-box--on::after { content: ""; }',
    ].join('\n');
    expect(markCopies('planted.css', planted)).toEqual([
        'planted.css: .x .oc-check__box -> width, border',
        'planted.css: [aria-checked=true] .oc-radio::after -> a mark of its own',
        'planted.css: .acm-box--on::after -> a mark of its own',
    ]);
});
