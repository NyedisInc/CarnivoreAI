import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, test } from 'vitest';

import enCatalog from '../../../../client/js/i18n/catalog.en.js';

/** Repo root, four levels up from web/src/lib/launchpad. */
const repoRoot = fileURLToPath(new URL('../../../..', import.meta.url));

const DELETE_WORD = /\bdelet(?:e|ed|ion)\b/i;

/* deleted on disk */
const REAL_DELETE_KEY_PREFIXES = [
    'skill.account.delete',
    'mail.account.deleted.',
    'admin.moderation.',
    'dashboards.delete',
    'dashboards.announce_deleted',
    'settings.ai.card.delete',
    'community.delete',
    'settings.stats.clear_failed',
    'approvals.display.verb.delete',
    'approvals.display.c.purge_gone',
    'approvals.display.c.project_deleted',
    'swarm.board.act.delete',
    'swarm.board.act.ok.delete',
    'swarm.board.delete.',
    'swarm.board.list.event.deleted',
    'sidebar.company.',
    'projects.page.action.delete',
    'projects.page.company.delete',
    'projects.page.project.delete',
    'git.changes.kind.deleted',
    'automations.',
    'bookmarks.delete',
    'bookmarks.hint',
    'widgets.info.more.bookmarks-all',
    'launch_profiles.action.',
    'settings.notify.dest.delete',
    'phoneLink.customDomain.dead.account_deleted',
    'account.guest.delete_label',
    'skills.command.remove.trash',
    'code_review.risk.delete',
    'cplug.huddle.completed.',
    'cplug.huddle.delete_confirm.',
    'opscenter.cell.task_manager_mk2.delete_closed',
    'analytics.delete',
    'opscenter.cell.files.open.deleted',
    'files.cant.gone',
    'files.editor.stale.deleted',
    'plugins.page.data.delete_files',
    'plugins.page.data.done',
    'widgets.places.row_label',
    'widgets.places.help',
    'deepsearch.state.backup',
    'deepsearch.tag.backup_tip',
];

const NON_COPY_DELETE_FRAGMENTS = new Map<string, string>([
    ['client/js/api-catalog.js', '/catalog/account/delete'],
    ['web/src/admin/moderation.ts', 'deleted account'],
    ['web/src/opscenter/layout-editor/ChartDeleteChip.svelte', '../cells/analytics/delete-chart'],
    ['client/js/menu-keys.js', 'delete (any delete-* id)'],
]);

function isRealDeleteKey(key: string): boolean {
    if (key.startsWith('settings.item.') && key.endsWith('.keywords')) return true;
    return REAL_DELETE_KEY_PREFIXES.some((p) => key.startsWith(p));
}

function realDeleteValues(): Set<string> {
    const out = new Set<string>();
    for (const [key, value] of Object.entries(enCatalog as Record<string, unknown>)) {
        if (!isRealDeleteKey(key)) continue;
        const forms = typeof value === 'string' ? [value] : Object.values((value ?? {}) as Record<string, string>);
        for (const f of forms) out.add(f);
    }
    return out;
}

function isPermittedDelete(v: { file: string; fragment: string }): boolean {
    if (NON_COPY_DELETE_FRAGMENTS.get(v.file) === v.fragment) return true;
    if (v.file === 'client/js/i18n/catalog.en.js' && realDeleteValues().has(v.fragment)) return true;
    const lines = v.fragment.split('\n').map((l) => l.trim()).filter(Boolean);
    if (lines.length > 0 && lines.every((l) => /^\{[#:@/][^]*\}$/.test(l))) return true;
    const ref = /^\{t\('([^']+)'(?:,\s*\{[^}]*\})?\)\}$/.exec(v.fragment.trim());
    if (ref !== null) return isRealDeleteKey(ref[1] ?? '');
    const call = /^\{t\((.*)\)\}$/.exec(v.fragment.trim());
    if (call === null) return false;
    const keys = [...(call[1] ?? '').matchAll(/'([^']+)'/g)].map((m) => m[1] ?? '');
    const catalog = enCatalog as Record<string, unknown>;
    return keys.length > 0 && keys.every((k) => isRealDeleteKey(k)
        || !DELETE_WORD.test(JSON.stringify(catalog[k] ?? '')));
}

const USER_FACING_ATTRS = ['title', 'aria-label', 'aria-description', 'placeholder', 'alt'];

const IDENTIFIER_SHAPE = /^[.#]?[a-zA-Z][a-zA-Z0-9]*(?:[.:_-]+[a-zA-Z0-9]+)*$/;

const BARE_INTERNAL_ATTR = /^(?:class|id|data-[a-zA-Z0-9-]+)=(["'])[^"']*\1$/;

const CODE_CHAR_BEFORE_REGEX = /[([{,;:=!&|?+\-*%^~<>]$/;
const KEYWORD_BEFORE_REGEX =
    /^(?:return|typeof|instanceof|in|of|new|delete|void|yield|case|do|else|throw)$/;

function isRegexLiteralStart(src: string, i: number): boolean {
    let k = i - 1;
    while (k >= 0 && /\s/.test(src.charAt(k))) k--;
    if (k < 0) return true;
    if (CODE_CHAR_BEFORE_REGEX.test(src.charAt(k))) return true;
    let wordStart = k;
    while (wordStart >= 0 && /[a-zA-Z_$]/.test(src.charAt(wordStart))) wordStart--;
    return KEYWORD_BEFORE_REGEX.test(src.slice(wordStart + 1, k + 1));
}

interface Literal { text: string; start: number }

function tokenizeStringLiterals(src: string): Literal[] {
    const out: Literal[] = [];
    const n = src.length;

    function walk(start: number, insideInterpolation: boolean): number {
        let i = start;
        let braceDepth = 0;
        while (i < n) {
            const c = src.charAt(i);
            const c2 = src.charAt(i + 1);
            if (c === '/' && c2 === '/') {
                i += 2;
                while (i < n && src[i] !== '\n') i++;
                continue;
            }
            if (c === '/' && c2 === '*') {
                i += 2;
                while (i < n && !(src[i] === '*' && src.charAt(i + 1) === '/')) i++;
                i += 2;
                continue;
            }
            if (c === '/' && isRegexLiteralStart(src, i)) {
                let j = i + 1;
                let inClass = false;
                while (j < n) {
                    if (src.charAt(j) === '\\') { j += 2; continue; }
                    if (src.charAt(j) === '[') { inClass = true; j++; continue; }
                    if (src.charAt(j) === ']') { inClass = false; j++; continue; }
                    if (src.charAt(j) === '/' && !inClass) break;
                    if (src.charAt(j) === '\n') break;
                    j++;
                }
                j++;
                while (j < n && /[a-zA-Z]/.test(src.charAt(j))) j++;
                i = j;
                continue;
            }
            if (c === '"' || c === "'") {
                const quote = c;
                const litStart = i;
                let j = i + 1;
                let buf = '';
                while (j < n && src.charAt(j) !== quote) {
                    if (src.charAt(j) === '\\') { buf += src.charAt(j + 1) || ''; j += 2; continue; }
                    buf += src.charAt(j);
                    j++;
                }
                out.push({ text: buf, start: litStart });
                i = j + 1;
                continue;
            }
            if (c === '`') {
                let j = i + 1;
                let buf = '';
                const litStart = i;
                while (j < n && src.charAt(j) !== '`') {
                    if (src.charAt(j) === '\\') { buf += src.charAt(j + 1) || ''; j += 2; continue; }
                    if (src.charAt(j) === '$' && src.charAt(j + 1) === '{') { j = walk(j + 2, true); continue; }
                    buf += src.charAt(j);
                    j++;
                }
                out.push({ text: buf, start: litStart });
                i = j + 1;
                continue;
            }
            if (insideInterpolation && c === '}' && braceDepth === 0) return i + 1;
            if (c === '{') { braceDepth++; i++; continue; }
            if (c === '}') { braceDepth--; i++; continue; }
            i++;
        }
        return i;
    }

    walk(0, false);
    return out;
}

function fragmentsOfMarkup(text: string): string[] {
    const fragments: string[] = [];
    for (const m of text.matchAll(/>([^<>]+)</g)) {
        const inner = (m[1] ?? '').trim();
        if (inner) fragments.push(inner);
    }
    for (const attr of USER_FACING_ATTRS) {
        for (const m of text.matchAll(new RegExp(`${attr}="([^"]*)"`, 'g'))) {
            fragments.push(m[1] ?? '');
        }
    }
    return fragments;
}

function userFacingFragmentsOf(text: string, precedingSrc: string): string[] {
    if (/console\s*\.\s*(?:log|warn|error|debug|info)\s*\($/.test(precedingSrc.trimEnd())) {
        return [];
    }
    const trimmed = text.trim();
    if (IDENTIFIER_SHAPE.test(trimmed) || BARE_INTERNAL_ATTR.test(trimmed)) return [];
    if (/<[a-zA-Z]/.test(text)) return fragmentsOfMarkup(text);
    return [text];
}

interface Violation { file: string; fragment: string }

function scanScript(rel: string): Violation[] {
    const src = fs.readFileSync(path.join(repoRoot, rel), 'utf8');
    const violations: Violation[] = [];
    for (const { text, start } of tokenizeStringLiterals(src)) {
        const preceding = src.slice(Math.max(0, start - 40), start);
        for (const fragment of userFacingFragmentsOf(text, preceding)) {
            if (DELETE_WORD.test(fragment)) violations.push({ file: rel, fragment });
        }
    }
    return violations;
}

function scanMarkup(rel: string): Violation[] {
    const raw = fs.readFileSync(path.join(repoRoot, rel), 'utf8');
    const stripped = raw
        .replace(/<!--[\s\S]*?-->/g, ' ')
        .replace(/\/\*[\s\S]*?\*\//g, ' ');
    const violations: Violation[] = [];
    const scripts = [...stripped.matchAll(/<script[^>]*>([\s\S]*?)<\/script>/g)];
    let markupOnly = stripped;
    for (const m of scripts) {
        markupOnly = markupOnly.replace(m[0], ' ');
        const body = m[1] ?? '';
        for (const { text, start } of tokenizeStringLiterals(body)) {
            const preceding = body.slice(Math.max(0, start - 40), start);
            for (const fragment of userFacingFragmentsOf(text, preceding)) {
                if (DELETE_WORD.test(fragment)) violations.push({ file: rel, fragment });
            }
        }
    }
    for (const fragment of fragmentsOfMarkup(markupOnly)) {
        if (DELETE_WORD.test(fragment)) violations.push({ file: rel, fragment });
    }
    return violations;
}

function listFiles(rel: string, exts: string[]): string[] {
    const out: string[] = [];
    const abs = path.join(repoRoot, rel);
    for (const entry of fs.readdirSync(abs, { withFileTypes: true })
        .sort((a, b) => a.name.localeCompare(b.name))) {
        const child = `${rel}/${entry.name}`;
        if (entry.isDirectory()) out.push(...listFiles(child, exts));
        else if (exts.some((e) => entry.name.endsWith(e))) out.push(child);
    }
    return out;
}

const scriptFiles = listFiles('client/js', ['.js']);
const webFiles = listFiles('web/src', ['.ts', '.svelte'])
    .filter((f) => !f.endsWith('.test.ts'));

describe('the legacy tree still says archive', () => {
    test('the walk is not silently empty', () => {
        expect(scriptFiles.length).toBeGreaterThan(100);
    });

    test('client/index.html has no delete-family copy', () => {
        expect(scanMarkup('client/index.html').map((v) => v.fragment)).toEqual([]);
    });

    test('no client/js file has delete-family copy', () => {
        const violations = scriptFiles.flatMap(scanScript).filter((v) => !isPermittedDelete(v));
        expect(violations).toEqual([]);
    });
});

describe('and so does the compiled tree, which is where slice 2 moved it', () => {
    test('the walk is not silently empty', () => {
        expect(webFiles.length).toBeGreaterThan(10);
    });

    test('no web/src source file has delete-family copy', () => {
        const violations = webFiles.flatMap((f) =>
            (f.endsWith('.svelte') ? scanMarkup : scanScript)(f)).filter((v) => !isPermittedDelete(v));
        expect(violations).toEqual([]);
    });
});

describe('and so does the catalog, which is where the copy actually lives now', () => {
    test('no catalog message says delete, deleted or deletion', () => {
        const offenders: string[] = [];
        for (const [key, value] of Object.entries(enCatalog as Record<string, unknown>)) {
            const forms = typeof value === 'string'
                ? [value]
                : Object.values((value ?? {}) as Record<string, string>);
            for (const form of forms) {
                if (isRealDeleteKey(key)) continue;
                if (DELETE_WORD.test(form)) offenders.push(`${key}: ${form}`);
            }
        }
        expect(offenders).toEqual([]);
    });

    test('the archive vocabulary is present, so the word was replaced not removed', () => {
        const values = Object.values(enCatalog as Record<string, unknown>)
            .flatMap((v) => (typeof v === 'string' ? [v] : Object.values(v as object)))
            .join('\n');
        expect(values).toMatch(/\barchive\b/);
        expect(values).toMatch(/\barchived\b/);
    });
});

describe('NEGATIVE CONTROL: the scanner finds a violation when there is one', () => {
    test('plain copy is caught', () => {
        expect(userFacingFragmentsOf('delete this session', '').filter((f) => DELETE_WORD.test(f)))
            .toEqual(['delete this session']);
    });

    test('copy inside markup is caught, and the identifier beside it is not', () => {
        const markup = '<button class="ended-session-delete" title="delete it">delete</button>';
        const found = fragmentsOfMarkup(markup).filter((f) => DELETE_WORD.test(f));
        expect(found.sort()).toEqual(['delete', 'delete it']);
    });

    test('an identifier, a dotted key and a console argument are never flagged', () => {
        expect(userFacingFragmentsOf('ended-session-delete', '')).toEqual([]);
        expect(userFacingFragmentsOf('carnivore.launchpad.deletedSessionsVisible', '')).toEqual([]);
        expect(userFacingFragmentsOf('the record was deleted', "console.warn(")).toEqual([]);
        expect(userFacingFragmentsOf('class="recent-session-row--deleted"', '')).toEqual([]);
    });

    test('a nested template literal does not corrupt the boundaries after it', () => {
        const src = 'const a = `<ul>${x ? `<li>archive</li>` : ""}</ul>`; const b = "delete it";';
        const texts = tokenizeStringLiterals(src).map((l) => l.text);
        expect(texts).toContain('delete it');
    });
});
