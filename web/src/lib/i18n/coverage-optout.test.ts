import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { walkSources } from '../../test-support/source-scan';

import { PORTED_FILES } from './ported-files';
import { looksLikeCopy, scannable, stringLiterals } from './string-scan';

const ROOT = path.resolve(__dirname, '../../../..');
const KNOWN_PATH = path.join(__dirname, 'uncovered-known.json');

const NOT_SCANNED = /\.(test|spec)\.|\.d\.ts$|\/fixtures\/|\/test-support\/|golden-cases\.ts$|^client\/js\/i18n\//;

const DIRECTIVES = new Set(['use strict']);

export function copyCount(text: string): number {
    return stringLiterals(scannable(text)).filter((one) => !DIRECTIVES.has(one) && looksLikeCopy(one)).length;
}

const walk = (dir: string): string[] => walkSources(dir, /./, { skipDirs: /^(node_modules|dist)$/, base: ROOT });

function scannedFiles(): string[] {
    const web = walk(path.join(ROOT, 'web/src')).filter((rel) => /\.(ts|svelte)$/.test(rel));
    const legacy = walk(path.join(ROOT, 'client/js')).filter((rel) => /\.m?js$/.test(rel));
    return [...web, ...legacy].filter((rel) => !NOT_SCANNED.test(rel));
}

describe('every UI source file is covered by the string guard by default', () => {
    const files = scannedFiles();
    const actual: Record<string, number> = {};
    for (const rel of files) {
        if (PORTED_FILES.includes(rel)) continue;
        const count = copyCount(fs.readFileSync(path.join(ROOT, rel), 'utf8'));
        if (count > 0) actual[rel] = count;
    }

    if (process.env['I18N_KNOWN_WRITE'] === '1') {
        const existing: Record<string, number> | null = fs.existsSync(KNOWN_PATH) ? JSON.parse(fs.readFileSync(KNOWN_PATH, 'utf8')) : null;
        const next = existing === null
            ? actual
            : Object.fromEntries(Object.entries(existing).flatMap(([rel, was]) => (actual[rel] ? [[rel, Math.min(was, actual[rel])]] : [])));
        fs.writeFileSync(KNOWN_PATH, JSON.stringify(Object.fromEntries(Object.entries(next).sort()), null, 1) + '\n');
    }
    const known: Record<string, number> = JSON.parse(fs.readFileSync(KNOWN_PATH, 'utf8'));

    it('looked at the source tree (a scan of nothing is not a pass)', () => {
        expect(files.length).toBeGreaterThan(1500);
        expect(files).toContain('client/js/router.js');
    });

    it('has no file with copy outside uncovered-known.json, and no file above its ceiling', () => {
        const bad = Object.entries(actual)
            .filter(([rel, count]) => count > (known[rel] ?? 0))
            .map(([rel, count]) => `${rel}: ${count} sentence-like literal(s), ceiling ${known[rel] ?? 0}`);
        expect(bad, 'put user-visible strings in client/js/i18n/catalog.en.js and read them with t()').toEqual([]);
    });

    it('keeps every row true (a ported or cleaned file lowers its row; see I18N_KNOWN_WRITE)', () => {
        const stale = Object.entries(known)
            .filter(([rel, ceiling]) => (actual[rel] ?? 0) < ceiling)
            .map(([rel, ceiling]) => `${rel}: ceiling ${ceiling}, now ${actual[rel] ?? 0}`);
        expect(stale).toEqual([]);
    });

    it('goes red on a fixture (negative control)', () => {
        expect(copyCount("const a = 'no sessions yet';")).toBe(1);
        expect(copyCount("'use strict'; t('session.none');\n// 'some prose here'")).toBe(0);
    });
});
