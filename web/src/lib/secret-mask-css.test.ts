/** @vitest-environment jsdom */
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, test } from 'vitest';
import { cssRules } from './base/css-rules';

const rules = cssRules(readFileSync(resolve(process.cwd(), 'src/opscenter/fields.css'), 'utf8'));

function masked(el: Element, value: string, pseudo: boolean): boolean {
    return rules.some((r) =>
        r.decls['-webkit-text-security'] === value &&
        r.selector.split(',').some((s) => {
            const sel = s.trim();
            if (pseudo !== sel.endsWith('::placeholder')) return false;
            return el.matches(sel.replace(/::placeholder$/, ''));
        }),
    );
}

function input(cls: string): HTMLInputElement {
    const el = document.createElement('input');
    el.className = cls;
    return el;
}

describe('secret mask selectors', () => {
    test('masks a base Field input that carries only oc-secret', () => {
        expect(masked(input('oc-secret'), 'disc', false)).toBe(true);
    });
    test('still masks the legacy oc-field oc-secret input', () => {
        expect(masked(input('oc-field oc-secret'), 'disc', false)).toBe(true);
    });
    test('does not mask a plain field', () => {
        expect(masked(input('oc-field'), 'disc', false)).toBe(false);
    });
    test('keeps the placeholder unmasked for oc-secret alone', () => {
        expect(masked(input('oc-secret'), 'none', true)).toBe(true);
    });
});
