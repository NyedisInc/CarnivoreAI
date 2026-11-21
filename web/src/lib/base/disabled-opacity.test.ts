import { readFileSync, readdirSync } from 'node:fs';
import { expect, test } from 'vitest';

import { cssRules } from './css-rules';

const TOKEN = 'var(--oc-disabled-opacity)';
const BASE_DIR = new URL('./', import.meta.url);
const SHARED_SHEETS = ['controls.css', 'fields.css', 'ui/tabs.css'];
const OPSCENTER = new URL('../../opscenter/', import.meta.url);

const DISABLED = /:disabled|\[data-disabled\]|\[aria-disabled=['"]?true['"]?\]/;

function withoutNegations(selector: string): string {
    return selector.replace(/:not\((?:[^()]|\([^()]*\))*\)/g, '');
}

function literalDisabledDims(name: string, css: string): string[] {
    return cssRules(css)
        .filter((r) => r.decls.opacity !== undefined && DISABLED.test(withoutNegations(r.selector)))
        .filter((r) => r.decls.opacity !== TOKEN)
        .map((r) => `${name}: ${r.selector} -> ${r.decls.opacity}`);
}

function sheets(): Array<[string, string]> {
    const base = readdirSync(BASE_DIR).filter((f) => f.endsWith('.css'));
    return [
        ...base.map((f): [string, string] => [`lib/base/${f}`, readFileSync(new URL(f, BASE_DIR), 'utf8')]),
        ...SHARED_SHEETS.map((f): [string, string] => [`opscenter/${f}`, readFileSync(new URL(f, OPSCENTER), 'utf8')]),
    ];
}

test('the token is declared once, in tokens.css', () => {
    const tokens = readFileSync(new URL('tokens.css', OPSCENTER), 'utf8');
    expect(tokens.match(/--oc-disabled-opacity:\s*[^;]+;/g)?.length).toBe(1);
});

test('every disabled control in the base and shared control sheets dims by the one token', () => {
    const all = sheets();
    expect(all.length).toBeGreaterThan(10);
    expect(all.flatMap(([name, css]) => literalDisabledDims(name, css))).toEqual([]);
});

test('negative control: a literal disabled dim is named, a hover guard is not', () => {
    const planted = '@layer base { .x:disabled { opacity: 0.35; } .y:hover:not(:disabled) { opacity: 0.4; } .z[data-disabled] { opacity: var(--oc-disabled-opacity); } }';
    expect(literalDisabledDims('planted.css', planted)).toEqual(['planted.css: .x:disabled -> 0.35']);
});
