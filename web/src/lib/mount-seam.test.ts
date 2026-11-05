import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { stripComments, walkSources } from '../test-support/source-scan';

const SRC = path.resolve(__dirname, '..');

const SEAMS = ['lib/mount.ts', 'lib/modal.ts'];

const DETACHED_KNOWN: Record<string, string> = {
    'main.ts': 'renderProbe: renders StatusLed into a div that is never inserted, to read its HTML, then unmounts',
    'admin/main.ts': 'the admin page is its own entry point and owns its document',
};

const TEST_ONLY = /\.(test|spec)\.|test-helpers\.ts$|-harness\.ts$/;

const sourceFiles = (dir: string): string[] => walkSources(dir, /\.(ts|svelte)$/, { exclude: TEST_ONLY, base: SRC });

export function findMountCalls(text: string): boolean {
    if (!/import\s*\{[^}]*\bmount\b[^}]*\}\s*from\s*['"]svelte['"]/.test(text)) return false;
    return /(^|[^.\w])mount\(/m.test(stripComments(text));
}

describe('only mount.ts and modal.ts call Svelte mount()', () => {
    const callers = sourceFiles(SRC).filter((file) => findMountCalls(fs.readFileSync(path.join(SRC, file), 'utf8')));

    it('has no caller outside the seam and DETACHED_KNOWN', () => {
        const bad = callers.filter((file) => !SEAMS.includes(file) && !(file in DETACHED_KNOWN));
        expect(bad, 'go through mountPanel / mountInto (lib/mount.ts) or openModal (lib/modal.ts)').toEqual([]);
    });

    it('keeps every DETACHED_KNOWN row true', () => {
        expect(Object.keys(DETACHED_KNOWN).filter((file) => !callers.includes(file))).toEqual([]);
    });

    it('goes red on a fixture (negative control)', () => {
        expect(findMountCalls("import { mount } from 'svelte';\nconst h = mount(A, { target });")).toBe(true);
        expect(findMountCalls("import { mount } from 'svelte';\n// mount(A)\n")).toBe(false);
        expect(findMountCalls('function mount() {}\nmount();')).toBe(false);
    });
});
