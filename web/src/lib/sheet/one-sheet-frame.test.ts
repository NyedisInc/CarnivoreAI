import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { expect, test } from 'vitest';

import { stripComments, walkSources } from '../../test-support/source-scan';

const WEB_SRC = new URL('../../', import.meta.url).pathname;
const REPO = new URL('../../../../', import.meta.url).pathname;
const FRAME = 'web/src/lib/sheet/Sheet.svelte';

const KNOWN_OWN_SHEETS: Record<string, number> = {
    'web/src/lib/automations/drawer/drawer.css': 1,
    'web/src/lib/automations/pane/pane.css': 1,
    'web/src/lib/session-rail/rail-layer.css': 1,
    'web/src/lib/session-skills/session-skills.css': 1,
};

const MIN_SHEET_PX = 48;
const POSITIONED = /^(?:fixed|absolute)$/;
const SKIP_DIRS = /^(?:node_modules|__goldens__|fixtures)$/;

function cssOf(path: string, text: string): string {
    const css = path.endsWith('.svelte') ? [...text.matchAll(/<style[^>]*>([\s\S]*?)<\/style>/g)].map((m) => m[1] ?? '').join('\n') : text;
    return stripComments(css);
}

function shorthand(value: string): string[] {
    const parts: string[] = [];
    let depth = 0;
    let part = '';
    for (const ch of value) {
        depth += ch === '(' ? 1 : ch === ')' ? -1 : 0;
        if (depth === 0 && /\s/.test(ch)) {
            if (part) parts.push(part);
            part = '';
        } else part += ch;
    }
    if (part) parts.push(part);
    return parts;
}

function declarations(body: string): Map<string, string> {
    const found = new Map<string, string>();
    for (const m of body.matchAll(/(?<![\w-])([a-z-]+)\s*:\s*([^;]+)/g)) found.set(m[1] ?? '', (m[2] ?? '').trim());
    return found;
}

function sheetWidth(width: string): boolean {
    if (/^(?:auto|100%|100vw)$/.test(width)) return false;
    const px = /^(\d+(?:\.\d+)?)px$/.exec(width);
    return px ? Number(px[1]) >= MIN_SHEET_PX : true;
}

function placesSheet(selector: string, body: string): boolean {
    if (/::?(?:before|after)\b/.test(selector)) return false;
    const d = declarations(body);
    const position = d.get('position') ?? '';
    if (!POSITIONED.test(position)) return false;
    const inset = shorthand(d.get('inset') ?? '');
    const pinned = (d.has('top') && d.has('right') && d.has('bottom')) || inset.length >= 3;
    const width = d.get('width');
    const noLeft = !d.has('left') && (inset.length < 4 || inset[3] === 'auto');
    if (pinned && width !== undefined && sheetWidth(width) && noLeft) return true;
    return position === 'fixed' && inset.length >= 3 && inset[0] !== '0' && inset.slice(1).every((v) => v === '0');
}

function sheetRules(css: string): number {
    return [...css.matchAll(/([^{}]*)\{([^{}]*)\}/g)].filter((m) => placesSheet(m[1] ?? '', m[2] ?? '')).length;
}

function counts(): Record<string, number> {
    const files = walkSources(WEB_SRC, /\.(?:css|svelte)$/, { skipDirs: SKIP_DIRS, base: REPO }).filter((f) => f !== FRAME);
    expect(files.length).toBeGreaterThan(300);
    const found: Record<string, number> = {};
    for (const f of files) {
        const n = sheetRules(cssOf(f, readFileSync(join(REPO, f), 'utf8')));
        if (n) found[f] = n;
    }
    return found;
}

test('no stylesheet places a side sheet of its own outside the known list, and the list is exact', () => {
    expect(counts()).toEqual(KNOWN_OWN_SHEETS);
});

test('the sessions panel, the automations reader and the layout editor drawer are on the frame', () => {
    for (const [file, place] of [
        ['web/src/lib/sessions-page/SessionPanel.svelte', 'page'],
        ['web/src/lib/automations/feed/ReaderSheet.svelte', 'column'],
        ['web/src/opscenter/layout-editor/WidgetDrawer.svelte', 'float'],
    ] as const) {
        expect(readFileSync(join(REPO, file), 'utf8'), file).toMatch(new RegExp(`<Sheet\\s[^>]*place="${place}"`));
    }
});

test('the frame owns one layer, one width scale and one phone edge', () => {
    const frame = readFileSync(join(REPO, FRAME), 'utf8');
    expect(frame.match(/z-index:\s*var\(--oc-z-sheet\)/g)?.length).toBe(3);
    expect(frame).toContain('width: var(--sheet-w, var(--oc-sheet-w))');
    expect(frame).toContain('inset: max(var(--overlay-top, 0px), env(safe-area-inset-top, 0px)) 0 0 0');
    expect(frame).not.toMatch(/z-index:\s*\d/);
});

test('negative control: each old sheet rule is named; an overlay, a toast, a hairline and a grip are not', () => {
    const planted = cssOf('x.css', [
        '/* .sp-pn { position: absolute; top: 0; right: 0; bottom: 0; width: 480px } */',
        '.sp-pn { position: absolute; top: 0; right: 0; bottom: 0; z-index: 6; width: var(--pn-w); }',
        '@media (max-width: 700px) { .ap-page .ap-dc { display: none; position: fixed; inset: var(--overlay-top, env(safe-area-inset-top, 0px)) 0 0 0; z-index: 40; } }',
        '.le-drawer { position: fixed; z-index: 40; top: 56px; right: 12px; bottom: 12px; width: 300px; }',
    ].join('\n'));
    expect(sheetRules(planted)).toBe(3);
    const quiet = cssOf('y.css', [
        '.modal-overlay { position: fixed; inset: 0; }',
        '.toast { position: fixed; right: 12px; bottom: 12px; width: 320px; }',
        '.edge::before { position: absolute; top: 0; right: 0; bottom: 0; width: 1px; }',
        '.grip { position: absolute; top: 0; right: 0; bottom: 0; width: 7px; }',
        '.bar { position: fixed; inset: 0 0 auto 0; }',
    ].join('\n'));
    expect(sheetRules(quiet)).toBe(0);
});
