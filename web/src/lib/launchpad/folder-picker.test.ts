import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, test } from 'vitest';

/** Repo root, four levels up from web/src/lib/launchpad. */
const repoRoot = fileURLToPath(new URL('../../../..', import.meta.url));

function repoFile(...parts: string[]): string {
    return fs.readFileSync(path.join(repoRoot, ...parts), 'utf8');
}

function codeOnly(src: string): string {
    return src
        .split('\n')
        .filter((line) => {
            const s = line.trim();
            return !s.startsWith('*') && !s.startsWith('//') && !s.startsWith('/*');
        })
        .join('\n');
}

describe('the extracted picker is still one module with one entry point', () => {
    const source = repoFile('client', 'js', 'folder-picker-modal.js');

    test('it publishes exactly the one entry point it promises', () => {
        expect(source).toMatch(/window\.FolderPickerModal\s*=/);
        expect(codeOnly(source)).toMatch(/open\s*[:(]/);
    });

    test('it reaches for no controller state', () => {
        expect(/\bthis\./.test(codeOnly(source))).toBe(false);
    });

    test('it carries its own escaper, so a caller need not inject one', () => {
        expect(codeOnly(source)).toMatch(/defaultEscapeHtml/);
    });

    test('nothing in the compiled tree keeps a second copy of the picker', () => {
        const host = repoFile('web', 'src', 'lib', 'launchpad', 'create-host.ts');
        expect(host).toMatch(/FolderPickerModal/);
        for (const file of ['ProjectFolderModal.svelte', 'open-folder-flow.ts']) {
            const src = repoFile('web', 'src', 'lib', 'launchpad', file);
            expect(src, file).not.toMatch(/folder-picker-toolbar/);
        }
    });

    test('the compiled tree opens it WITHOUT injecting an escaper', () => {
        const host = codeOnly(repoFile('web', 'src', 'lib', 'launchpad', 'create-host.ts'));
        expect(host).toMatch(/picker\.open\(\)/);
        expect(host).not.toMatch(/escapeHtml/);
    });

    test('launchpad.js is gone, so nothing legacy can reach it', () => {
        expect(fs.existsSync(path.join(repoRoot, 'client/js/launchpad.js'))).toBe(false);
    });

    test('the index page still loads it, and before the bundle', () => {
        const html = repoFile('client', 'index.html');
        const picker = html.indexOf('/static/js/folder-picker-modal.js');
        const bundle = html.indexOf('/static/dist/app.js');
        expect(picker, 'folder-picker-modal.js is never loaded at all').not.toBe(-1);
        expect(bundle, 'the bundle is never loaded at all').not.toBe(-1);
        expect(picker).toBeLessThan(bundle);
    });

    test('project-create-folder.js is gone, and nothing still loads it', () => {
        expect(fs.existsSync(path.join(repoRoot, 'client/js/project-create-folder.js'))).toBe(
            false,
        );
        expect(repoFile('client', 'index.html')).not.toMatch(
            /<script[^>]*project-create-folder\.js/,
        );
    });
});

// ---- the stylesheet contract ----------------------------------------

interface Rule {
    selector: string;
    body: string;
}

function rules(source: string): Rule[] {
    const clean = source.replace(/\/\*[\s\S]*?\*\//g, '');
    const out: Rule[] = [];
    const re = /([^{}]+)\{([^{}]*)\}/g;
    let m: RegExpExecArray | null;
    while ((m = re.exec(clean)) !== null) {
        const selector = m[1]!.trim().replace(/\s+/g, ' ');
        if (!selector || selector.startsWith('@')) continue;
        out.push({ selector, body: m[2] ?? '' });
    }
    return out;
}

function bySelector(ruleList: Rule[], wanted: string): Rule[] {
    return ruleList.filter((r) => r.selector.split(',').some((s) => s.trim() === wanted));
}

function decl(body: string, prop: string): string | null {
    const m = body.match(new RegExp(`(?:^|;)\\s*${prop}\\s*:\\s*([^;]+)`, 'i'));
    return m ? m[1]!.trim() : null;
}

describe('a full path wraps rather than overrunning its box', () => {
    const styleRules = rules(repoFile('client', 'css', 'styles.css'));

    test('.folder-picker-path wraps', () => {
        const hits = bySelector(styleRules, '.folder-picker-path');
        expect(hits, 'expected exactly one `.folder-picker-path` base rule').toHaveLength(1);
        expect(decl(hits[0]!.body, 'word-break')).toBe('break-all');
        expect(decl(hits[0]!.body, 'overflow-wrap')).toBeTruthy();
    });

    test('it matches .folder-picker-status wrap treatment', () => {
        const pathRule = bySelector(styleRules, '.folder-picker-path')[0]!;
        const status = bySelector(styleRules, '.folder-picker-status')[0]!;
        expect(status, '.folder-picker-status rule not found').toBeTruthy();
        expect(decl(pathRule.body, 'word-break')).toBe(decl(status.body, 'word-break'));
    });

    test('the dead :focus and ::placeholder rules on it are gone', () => {
        expect(bySelector(styleRules, '.folder-picker-path:focus')).toEqual([]);
        expect(bySelector(styleRules, '.folder-picker-path::placeholder')).toEqual([]);
    });

    test('.modal-input still supplies real :focus and ::placeholder styling', () => {
        const focus = bySelector(styleRules, '.modal-input:focus');
        const placeholder = bySelector(styleRules, '.modal-input::placeholder');
        expect(focus.length, '.modal-input:focus rule not found').toBeGreaterThan(0);
        expect(placeholder.length, '.modal-input::placeholder rule not found').toBeGreaterThan(0);
        expect(decl(focus[0]!.body, 'box-shadow')).toBeTruthy();
        expect(decl(placeholder[0]!.body, 'color')).toBeTruthy();
    });
});
