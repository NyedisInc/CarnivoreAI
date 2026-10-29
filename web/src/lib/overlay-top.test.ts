import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, test } from 'vitest';

/** The repo root, from this file. */
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');

const OVERLAYS: ReadonlyArray<{ file: string; selector: string }> = [
    { file: 'web/src/opscenter/page.css', selector: '.oc-page' },
];

function uncommented(rel: string): string {
    return fs.readFileSync(path.join(ROOT, rel), 'utf8').replace(/\/\*[\s\S]*?\*\//g, '');
}

function ruleBody(css: string, selector: string): string {
    const pattern = new RegExp(`(^|[\\s},])${selector.replace(/\./g, '\\.')}\\s*(?:,[^{}]*)?\\{([^}]*)\\}`, 'g');
    return [...css.matchAll(pattern)].map((m) => m[2]).join('\n');
}

describe('the overlays share one top edge', () => {
    test.each(OVERLAYS)('$file positions from var(--overlay-top) alone', ({ file, selector }) => {
        const rule = ruleBody(uncommented(file), selector);
        expect(rule).toMatch(/position:\s*fixed/);
        const tops = rule.match(/(^|[\s;])top:\s*[^;]+;/g) ?? [];
        expect(tops.map((t) => t.trim().replace(/^;/, '').trim())).toEqual(['top: var(--overlay-top);']);
    });

    test('the token is the shared header height off the home screen', () => {
        expect(ruleBody(uncommented('client/css/styles.css'), ':root')).toMatch(
            /--overlay-top:\s*var\(--header-h\);/,
        );
    });

    test('and the dashboard top bar while the dashboard is up', () => {
        expect(ruleBody(uncommented('client/css/launchpad-host.css'), 'body.home-opscenter')).toMatch(
            /--overlay-top:\s*var\(--oc-topbar\);/,
        );
    });
});
