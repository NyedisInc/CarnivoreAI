import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';
import { expect, test } from 'vitest';

import { cssRules } from './css-rules';

const SRC = new URL('../../', import.meta.url).pathname;
const RECIPE = ['lib/base/icon-button.css', 'lib/base/elements.css'];
const TWINS: Array<[string, string]> = [
    ["[data-btn][data-size='icon']", '.oc-ibtn'],
    ["[data-btn='quiet'][data-size='icon']", '.oc-ibtn--bare'],
    ["[data-tone='close']", '.oc-ibtn--close'],
    ["[data-tone='float']", '.oc-ibtn--float'],
];
const NO_TWIN = ["[data-tone='danger']", "[data-tone='strong']"];
const FAMILY_RULE = /^(?::where\()?\.oc-ibtn(?:--[\w-]+)?(?![\w-])[^\s>+~]*$/;

function missingTwins(css: string): string[] {
    return cssRules(css).flatMap((rule) =>
        TWINS.filter(([attr, cls]) => rule.selector.includes(attr) && !rule.selector.includes(cls) && !NO_TWIN.some((n) => rule.selector.includes(n))).map(
            ([attr, cls]) => `${attr} missing ${cls}: ${rule.selector}`,
        ),
    );
}

function familyCopies(name: string, css: string): string[] {
    return cssRules(css).flatMap((rule) =>
        rule.selector
            .split(',')
            .map((one) => one.trim().replace(/:global\(([^()]*)\)/g, '$1'))
            .filter((one) => FAMILY_RULE.test(one))
            .map((one) => `${name}: ${one}`),
    );
}

function walk(dir: string): string[] {
    return readdirSync(dir).flatMap((name) => {
        const path = join(dir, name);
        if (name === 'node_modules' || name === '__goldens__') return [];
        if (statSync(path).isDirectory()) return walk(path);
        return name.endsWith('.css') || name.endsWith('.svelte') ? [relative(SRC, path)] : [];
    });
}

/**
 * The style text of a source file: a stylesheet whole, a Svelte component's <style> blocks.
 *
 * Inputs: text (string); svelte (boolean). Output: string.
 */
function styleOf(text: string, svelte: boolean): string {
    if (!svelte) return text;
    return [...text.matchAll(/<style[^>]*>([\s\S]*?)<\/style>/g)].map((m) => m[1] ?? '').join('\n');
}

test('every icon button variant of the recipe also draws its .oc-ibtn class twin', () => {
    const css = readFileSync(join(SRC, 'lib/base/icon-button.css'), 'utf8');
    expect(css).toContain('.oc-ibtn--float');
    expect(missingTwins(css)).toEqual([]);
});

test('the shared button rules (defaults, box, colors, hover, disabled) reach .oc-ibtn', () => {
    const rules = cssRules(readFileSync(join(SRC, 'lib/base/elements.css'), 'utf8'));
    const reach = rules.filter((r) => r.selector.includes('.oc-ibtn'));
    expect(reach.some((r) => r.selector.includes(':hover'))).toBe(true);
    expect(reach.some((r) => r.selector.includes(':disabled'))).toBe(true);
    expect(reach.some((r) => r.decls.background !== undefined || r.decls['background-color'] !== undefined)).toBe(true);
});

test('no sheet outside the recipe defines the .oc-ibtn family', () => {
    const files = walk(SRC).filter((f) => !RECIPE.includes(f));
    expect(files.length).toBeGreaterThan(100);
    const copies = files.flatMap((f) => familyCopies(f, styleOf(readFileSync(join(SRC, f), 'utf8'), f.endsWith('.svelte'))));
    expect(copies).toEqual([]);
});

test('negative control: a missing twin and a planted family copy are named, a placed one is not', () => {
    const variants = ":where([data-btn='quiet'][data-size='icon']) { --_btn-ink: red; } :where([data-btn][data-size='icon'][data-tone='danger']) { --_btn-ink: red; }";
    expect(missingTwins(variants)).toEqual([
        "[data-btn='quiet'][data-size='icon'] missing .oc-ibtn--bare: :where([data-btn='quiet'][data-size='icon'])",
    ]);
    const planted = '.oc-ibtn { width: 20px; } .oc-ibtn--bare:hover:not(:disabled) { color: red; } .hd .oc-ibtn { width: 1px; }';
    expect(familyCopies('planted.css', planted)).toEqual([
        'planted.css: .oc-ibtn',
        'planted.css: .oc-ibtn--bare:hover:not(:disabled)',
    ]);
});
