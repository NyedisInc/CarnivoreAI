/** @vitest-environment jsdom */
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, test } from 'vitest';

const css = readFileSync(resolve(process.cwd(), 'src/lib/base/elements.css'), 'utf8').replace(/\/\*[\s\S]*?\*\//g, '');

function splitTop(list: string): string[] {
    const out: string[] = [];
    let depth = 0;
    let cur = '';
    for (const ch of list) {
        if (ch === '(' || ch === '[') depth++;
        if (ch === ')' || ch === ']') depth--;
        if (ch === ',' && depth === 0) {
            out.push(cur.trim());
            cur = '';
        } else cur += ch;
    }
    out.push(cur.trim());
    return out;
}

function entriesOf(marker: string): string[] {
    const i = css.indexOf(marker);
    expect(i, `rule with ${marker} exists`).toBeGreaterThan(-1);
    const head = css.slice(css.lastIndexOf('}', i) + 1, css.lastIndexOf('{', i)).trim();
    expect(head.startsWith(':where(') && head.endsWith(')')).toBe(true);
    return splitTop(head.slice(':where('.length, -1));
}

function wears(entries: string[], el: Element): boolean {
    return entries.some((e) => {
        try {
            return el.matches(e);
        } catch {
            return false;
        }
    });
}

const btn = (cls: string): Element => {
    const b = document.createElement('button');
    b.className = cls;
    return b;
};

describe('bare .modal-btn', () => {
    const colors = entriesOf('--_btn-edge: var(--oc-line-button)');
    const hover = entriesOf('border-color: var(--_btn-edge-hover)').map((e) => e.replaceAll(':hover', ''));

    test('gets the secondary colors and hover', () => {
        expect(wears(colors, btn('modal-btn'))).toBe(true);
        expect(wears(hover, btn('modal-btn'))).toBe(true);
    });

    test('a variant is matched by its own entry, never by the bare one', () => {
        const bareOnly = colors.filter((e) => e.includes(':not([class*='));
        expect(bareOnly.length).toBe(1);
        for (const v of ['danger', 'confirm', 'primary', 'secondary', 'alert']) {
            expect(wears(bareOnly, btn(`modal-btn modal-btn-${v}`)), v).toBe(false);
            expect(wears(colors, btn(`modal-btn modal-btn-${v}`)), v).toBe(true);
        }
    });

    test('danger, confirm and primary keep their variant rules', () => {
        expect(wears(entriesOf('--_bd: var(--oc-coral)'), btn('modal-btn modal-btn-danger'))).toBe(true);
        expect(wears(entriesOf('--_btn-fill-hover: var(--oc-orange-tint);\n    --_btn-ink-hover'), btn('modal-btn modal-btn-confirm'))).toBe(true);
        expect(wears(entriesOf('--_btn-fill: var(--oc-orange-tint)'), btn('modal-btn modal-btn-primary'))).toBe(true);
    });
});
