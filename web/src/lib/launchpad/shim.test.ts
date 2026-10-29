import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, test } from 'vitest';

import { SHIM_MEMBERS } from './shim';

/** Repo root, four levels up from web/src/lib/launchpad. */
const repoRoot = fileURLToPath(new URL('../../../..', import.meta.url));

function legacyFiles(dir: string): string[] {
    const out: string[] = [];
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
        const full = path.join(dir, entry.name);
        if (entry.isDirectory()) out.push(...legacyFiles(full));
        else if (entry.name.endsWith('.js')) out.push(full);
    }
    return out;
}

function compiledFiles(dir: string): string[] {
    const out: string[] = [];
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
        const full = path.join(dir, entry.name);
        if (entry.isDirectory()) { out.push(...compiledFiles(full)); continue; }
        if (entry.name.includes('.test.')) continue;
        if (entry.name === 'shim.ts') continue;
        if (/\.(ts|svelte)$/.test(entry.name)) out.push(full);
    }
    return out;
}

function code(src: string): string {
    return src
        .replace(/\/\*[\s\S]*?\*\//g, ' ')
        .replace(/^[ \t]*\/\/.*$/gm, ' ');
}

function legacyUses(): Map<string, string[]> {
    const uses = new Map<string, string[]>();
    const files = [
        ...legacyFiles(path.join(repoRoot, 'client', 'js')),
        ...compiledFiles(path.join(repoRoot, 'web', 'src')),
    ];
    for (const file of files) {
        const rel = path.relative(repoRoot, file);
        const src = code(fs.readFileSync(file, 'utf8'));
        for (const member of membersReachedIn(src)) {
            const seen = uses.get(member) ?? [];
            if (!seen.includes(rel)) seen.push(rel);
            uses.set(member, seen);
        }
    }
    return uses;
}

function aliasesIn(src: string): Set<string> {
    const aliases = new Set<string>(['window.Launchpad', 'globalThis.Launchpad']);
    const decl = /(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*(?::[^=;]{0,160})?=\s*([\s\S]{0,300}?);/g;
    for (let changed = true, guard = 0; changed && guard < 8; guard++) {
        changed = false;
        decl.lastIndex = 0;
        let m: RegExpExecArray | null;
        while ((m = decl.exec(src)) !== null) {
            const name = m[1] ?? '';
            const rhs = m[2] ?? '';
            if (!name || aliases.has(name)) continue;
            const direct = /\.Launchpad\b/.test(rhs);
            const viaAlias = [...aliases].some(
                (a) => !a.includes('.') && new RegExp(`\\b${a}\\s*\\(`).test(rhs),
            );
            if (direct || viaAlias) { aliases.add(name); changed = true; }
        }
        for (const fn of returningFunctions(src, aliases)) {
            if (fn && !aliases.has(fn)) { aliases.add(fn); changed = true; }
        }
    }
    return aliases;
}

function returningFunctions(src: string, aliases: Set<string>): string[] {
    const out: string[] = [];
    const head = /function\s+([A-Za-z_$][\w$]*)\s*\([^)]*\)\s*(?::[^{]+)?\{/g;
    let m: RegExpExecArray | null;
    while ((m = head.exec(src)) !== null) {
        let depth = 1;
        let i = head.lastIndex;
        while (i < src.length && depth > 0) {
            if (src[i] === '{') depth++;
            else if (src[i] === '}') depth--;
            i++;
        }
        const body = src.slice(head.lastIndex, i);
        const ret = /\breturn\b([^;]*);/g;
        let r: RegExpExecArray | null;
        while ((r = ret.exec(body)) !== null) {
            const expr = r[1] ?? '';
            const calls = [...aliases].some(
                (a) => !a.includes('.') && new RegExp(`\\b${a}\\s*\\(`).test(expr),
            );
            if (/\.Launchpad\b/.test(expr) || calls) out.push(m[1] ?? '');
        }
    }
    return out;
}

function membersReachedIn(src: string): Set<string> {
    const found = new Set<string>();
    for (const alias of aliasesIn(src)) {
        const base = alias.replace(/\./g, '\\.');
        const re = new RegExp(`\\b${base}\\s*(?:\\(\\s*\\))?\\??\\.([A-Za-z_][\\w]*)`, 'g');
        let m: RegExpExecArray | null;
        while ((m = re.exec(src)) !== null) {
            const member = m[1] ?? '';
            if (member) found.add(member);
        }
    }
    const destructure = /(?:const|let|var)\s*\{([^}]*)\}\s*=\s*([^;]{0,200});/g;
    let d: RegExpExecArray | null;
    while ((d = destructure.exec(src)) !== null) {
        const rhs = d[2] ?? '';
        const viaAlias = /\.Launchpad\b/.test(rhs)
            || [...aliasesIn(src)].some(
                (a) => !a.includes('.') && new RegExp(`\\b${a}\\s*\\(`).test(rhs),
            );
        if (!viaAlias) continue;
        for (const part of (d[1] ?? '').split(',')) {
            const key = part.split(':')[0]?.trim().replace(/^\.\.\./, '').replace(/\s*=.*$/, '');
            if (key) found.add(key);
        }
    }
    return found;
}

const KNOWN_GAPS: ReadonlyMap<string, string> = new Map();

describe('client/js/launchpad.js is gone', () => {
    test('the file does not exist', () => {
        expect(fs.existsSync(path.join(repoRoot, 'client/js/launchpad.js'))).toBe(false);
    });

    test('and client/index.html does not try to load it', () => {
        const html = fs.readFileSync(path.join(repoRoot, 'client/index.html'), 'utf8');
        expect(html).not.toContain('src="/static/js/launchpad.js"');
    });

    test('nothing in client/js constructs a Launchpad of its own', () => {
        for (const file of legacyFiles(path.join(repoRoot, 'client', 'js'))) {
            expect(code(fs.readFileSync(file, 'utf8')), file).not.toMatch(
                /window\.Launchpad\s*=\s*new\b/,
            );
        }
    });
});

describe('the shim and its callers agree, in both directions', () => {
    test('every member the legacy tree uses is on the shim', () => {
        const uses = legacyUses();
        const missing = [...uses.keys()].filter(
            (member) => !SHIM_MEMBERS.includes(member) && !KNOWN_GAPS.has(member),
        );
        expect(
            missing,
            `these are reached in client/js and the shim does not carry them: ${JSON.stringify(
                [...uses.entries()].filter(([m]) => missing.includes(m)),
            )}`,
        ).toEqual([]);
    });

    test('and every member on the shim is actually reached', () => {
        const uses = legacyUses();
        const unused = SHIM_MEMBERS.filter((member) => !uses.has(member));
        expect(unused, `the shim carries members nothing uses: ${unused.join(', ')}`).toEqual([]);
    });

    test('the set is what slice 7 measured, not what the plan predicted', () => {
        expect([...SHIM_MEMBERS].sort()).toEqual([
            '_deriveRunningSessionDisplayName',
            'init',
            'launchpadScreen',
            'loadProjects',
            'loadRunningSessions',
            'openProjectByName',
            'selectProject',
            'showError',
            'showProviderModal',
        ]);
    });

    test('NEGATIVE CONTROL: the grep really does find a use', () => {
        const uses = legacyUses();
        expect(uses.get('openProjectByName')).toContain('client/js/router.js');
        expect(uses.get('init')).toContain('client/js/app.js');
        expect(uses.get('showProviderModal')).toContain('client/js/providers.js');
    });

    test('NEGATIVE CONTROL: the scanner really does see through an alias', () => {
        const uses = legacyUses();
        const seen = uses.get('showError') ?? [];
        expect(seen).toContain('web/src/lib/launchpad/recent-actions.ts');
        expect(seen).toContain('web/src/lib/launchpad/running-host.ts');
        expect(seen).toContain('web/src/lib/item-menu/run/run-env.ts');
        expect(uses.get('selectProject') ?? []).toContain('web/src/lib/item-menu/run/folder-actions.ts');
    });

    test('NEGATIVE CONTROL: an alias to something else is not an alias to the shim', () => {
        const decoy = 'const notTheShim = window.SomethingElse; notTheShim.totallyMadeUpMember();';
        expect([...membersReachedIn(decoy)]).not.toContain('totallyMadeUpMember');
    });
});

describe('the three call sites slice 6 left are resolved, not forwarded', () => {
    const read = (rel: string) => code(fs.readFileSync(path.join(repoRoot, rel), 'utf8'));

    test('providers.js draws no markup of its own and never reaches the shim for an escape helper', () => {
        const src = read('client/js/providers.js');
        expect(src).not.toContain('Launchpad._escapeHtml');
        expect(src).not.toContain('innerHTML');
    });

    test('providers.js confirms nothing through the shim', () => {
        const src = read('client/js/providers.js');
        expect(src).not.toContain('Launchpad.showConfirmModal');
        expect(src).not.toContain('showConfirmModal');
    });
});
