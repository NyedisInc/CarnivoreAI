import { describe, expect, test } from 'vitest';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative, resolve } from 'node:path';

const ROOT = resolve(__dirname, '../../../..');
const SCAN = ['web/src', 'client/js'];

const ALLOWED: ReadonlySet<string> = new Set([
    'client/js/labels/catalog-kind.js',
    'web/src/lib/catalog/card.ts',
    'web/src/lib/catalog/kind-display.ts',
    'web/src/lib/plugins-page/cplugs-adapter.ts',
    'web/src/lib/plugins-page/plugin-uninstall.ts',
]);

function walk(dir: string): string[] {
    return readdirSync(dir).flatMap((name) => {
        const full = join(dir, name);
        if (statSync(full).isDirectory()) return name === 'node_modules' || name === 'dist' ? [] : walk(full);
        return /\.(ts|js|svelte)$/.test(name) && !/\.test\.(ts|js)$/.test(name) ? [full] : [];
    });
}

describe('guard G2: no raw cplug literal outside the allow-list', () => {
    test('every display grouping goes through displayKind', () => {
        const hits = SCAN.flatMap((dir) => walk(join(ROOT, dir)))
            .filter((file) => /['"]cplug['"]/.test(readFileSync(file, 'utf8')))
            .map((file) => relative(ROOT, file))
            .sort();
        expect(hits.filter((file) => !ALLOWED.has(file))).toEqual([]);
        // no longer holds
        expect([...ALLOWED].filter((file) => !hits.includes(file))).toEqual([]);
    });
});
