/** @vitest-environment jsdom */
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, test } from 'vitest';

const css = readFileSync(resolve(process.cwd(), 'src/lib/base/elements.css'), 'utf8').replace(/\/\*[\s\S]*?\*\//g, '');

function fieldCompounds(): string[] {
    const out: string[] = [];
    const re = /\[data-field\]/g;
    let m: RegExpExecArray | null;
    while ((m = re.exec(css))) {
        let start = m.index;
        let depth = 0;
        while (start > 0) {
            const ch = css[start - 1]!;
            if (ch === ')') depth++;
            else if (ch === '(') {
                if (depth === 0) break;
                depth--;
            } else if (depth === 0 && !/[A-Za-z0-9_:\-]/.test(ch)) break;
            start--;
        }
        out.push(css.slice(start, m.index + m[0].length));
    }
    return out;
}

const matchesAny = (el: Element): boolean =>
    fieldCompounds().some((sel) => {
        try {
            return el.matches(sel);
        } catch {
            return false;
        }
    });

describe('data-field scope in the base layer', () => {
    test('the sheet has data-field rules to test', () => {
        expect(fieldCompounds().length).toBeGreaterThan(3);
    });

    test('a span carrying data-field matches no base field rule', () => {
        const span = document.createElement('span');
        span.setAttribute('data-field', 'cwd');
        expect(matchesAny(span)).toBe(false);
    });

    test.each(['input', 'select', 'textarea'])('a %s carrying data-field still matches', (tag) => {
        const el = document.createElement(tag);
        el.setAttribute('data-field', '');
        expect(matchesAny(el)).toBe(true);
    });
});
