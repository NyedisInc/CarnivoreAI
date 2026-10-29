import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, test } from 'vitest';

const HERE = path.dirname(fileURLToPath(import.meta.url));

function sources(): string[] {
    return fs
        .readdirSync(HERE)
        .filter((name) => name.endsWith('.ts') || name.endsWith('.svelte'))
        .filter((name) => !name.endsWith('.test.ts'))
        .sort();
}

function stripComments(source: string): string {
    return source
        .replace(/\/\*[\s\S]*?\*\//g, ' ')
        .replace(/<!--[\s\S]*?-->/g, ' ')
        .replace(/^\s*\/\/.*$/gm, ' ');
}

const HASHING = ['crypto.subtle', 'createHash', 'webcrypto', 'SubtleCrypto'];

describe('the client echoes, it never computes', () => {
    test('POSITIVE CONTROL: the stripper leaves real code standing', () => {
        const stripped = stripComments(
            fs.readFileSync(path.join(HERE, 'scripts.ts'), 'utf8'),
        );
        expect(stripped).toContain('export function consentBlock');
        expect(stripped).toContain('preview.digest');
        expect(stripped).not.toContain('undefined outside a secure context');
    });

    test('it scans every shipped source on this surface', () => {
        const names = sources();
        expect(names).toContain('scripts.ts');
        expect(names).toContain('DetailActions.svelte');
        expect(names).toContain('InstallSheet.svelte');
        expect(names).toContain('installed-actions.ts');
        expect(names.length).toBeGreaterThan(20);
    });

    test('no shipped source calls a hashing API', () => {
        const offenders: string[] = [];
        for (const name of sources()) {
            const code = stripComments(
                fs.readFileSync(path.join(HERE, name), 'utf8'),
            );
            for (const api of HASHING) {
                if (code.includes(api)) offenders.push(`${name}: ${api}`);
            }
        }
        expect(offenders).toEqual([]);
    });
});
