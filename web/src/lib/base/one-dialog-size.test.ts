import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { expect, test } from 'vitest';

import { walkSources } from '../../test-support/source-scan';
import { cssRules } from './css-rules';

const WEB_SRC = new URL('../../', import.meta.url).pathname;
const REPO = new URL('../../../../', import.meta.url).pathname;
const BASE = 'web/src/lib/base/elements.css';
const KNOWN: Record<string, number> = {
    'web/src/lib/catalog/AccountPanel.svelte': 1,
    'web/src/lib/catalog/CardImageRow.svelte': 1,
    'web/src/lib/catalog/ItemNoteForm.svelte': 1,
    'web/src/lib/catalog/ItemNotePopup.svelte': 1,
    'web/src/lib/catalog/RatingControl.svelte': 1,
    'web/src/lib/catalog/SessionsPanel.svelte': 1,
    'web/src/lib/pack-roster/roster.css': 1,
    'web/src/lib/skill-page/skill-page.css': 1,
    'web/src/lib/deepsearch/ContextModal.svelte': 1,
    'web/src/opscenter/page.css': 1,
};
const DIALOG_BUTTON = /\.(?:modal-btn(?:-(?:danger|confirm|secondary|primary|alert))?|oc-btn)(?![\w-])/;
const SIZES = /^(?:padding(?:-\w+)*|font-size|--_btn-pad(?:-y)?|--_btn-fs)$/;
const STYLE_FILE = /\.(?:css|svelte)$/;
const SKIP_DIRS = /^(?:node_modules|__goldens__)$/;

function styleSources(dir: string): string[] {
    return walkSources(dir, STYLE_FILE, { skipDirs: SKIP_DIRS, base: REPO });
}

/**
 * The style text of a source file: a stylesheet whole, a Svelte component's <style> blocks.
 *
 * Inputs: text (string); svelte (boolean). Output: string.
 */
function styleOf(text: string, svelte: boolean): string {
    if (!svelte) return text;
    return [...text.matchAll(/<style[^>]*>([\s\S]*?)<\/style>/g)].map((m) => m[1] ?? '').join('\n');
}

function subject(selector: string): string {
    const plain = selector.replace(/:global\(([^()]*)\)/g, '$1').replace(/:(?:not|is|where|has)\((?:[^()]|\([^()]*\))*\)/g, '');
    const parts = plain.trim().split(/\s*[\s>+~]\s*/);
    return parts[parts.length - 1] ?? '';
}

function dialogSizes(name: string, css: string): string[] {
    return cssRules(css).flatMap((rule) => {
        const sized = Object.keys(rule.decls).filter((p) => SIZES.test(p));
        if (!sized.length) return [];
        const hit = rule.selector.split(',').find((one) => DIALOG_BUTTON.test(subject(one)));
        return hit ? [`${name}: ${hit.trim()} -> ${sized.join(', ')}`] : [];
    });
}

function sizedFiles(): Record<string, number> {
    const files = [...styleSources(WEB_SRC), ...styleSources(join(REPO, 'client/css'))].filter((f) => f !== BASE);
    expect(files.length).toBeGreaterThan(200);
    const counts: Record<string, number> = {};
    for (const f of files) {
        const n = dialogSizes(f, styleOf(readFileSync(join(REPO, f), 'utf8'), f.endsWith('.svelte'))).length;
        if (n) counts[f] = n;
    }
    return counts;
}

test('the base sets one medium for every class button family, the restart picker footer size', () => {
    const rules = cssRules(readFileSync(join(REPO, BASE), 'utf8'));
    const medium = rules.filter((r) => r.decls['--_btn-pad-y'] === 'var(--oc-btn-pad-y)');
    expect(medium).toHaveLength(1);
    for (const cls of ['.oc-btn', '.modal-btn', '.modal-btn-danger', '.modal-btn-confirm']) expect(medium[0]!.selector).toContain(cls);
    expect(medium[0]!.decls['--_btn-pad']).toBe('var(--oc-space-4)');
    expect(medium[0]!.decls['--_btn-fs']).toBe('var(--oc-fs-control)');
    const tokens = readFileSync(join(WEB_SRC, 'opscenter/tokens.css'), 'utf8');
    expect(tokens).toMatch(/--oc-btn-pad-y:\s*7px;/);
});

test('a region asks for the compact size, an icon square keeps its own', () => {
    const rules = cssRules(readFileSync(join(REPO, BASE), 'utf8'));
    const compact = rules.find((r) => r.selector.includes("[data-btn-density='compact']"))!;
    expect(compact.decls['--_btn-h']).toBe('var(--oc-control-h-sm)');
    expect(compact.selector).toContain('[data-btn]:not([data-size])');
});

test('no dialog or page sheet sizes a dialog button outside the known list, and the list is exact', () => {
    expect(sizedFiles()).toEqual(KNOWN);
});

test('negative control: a planted dialog size is named, a placement, a tap floor or a modifier is not', () => {
    const planted = [
        '.x .modal-btn { padding: 7px 16px; font-size: 13px; }',
        '.x :global(.modal-footer .modal-btn-confirm:disabled) { --_btn-pad: 2px; }',
        '.x .modal-btn { flex: none; min-height: 44px; }',
        '.oc-btn--sm { --_btn-pad: 7px; }',
        '.modal-btn-row { padding: 4px; }',
    ].join('\n');
    expect(dialogSizes('planted.css', planted)).toEqual([
        'planted.css: .x .modal-btn -> padding, font-size',
        'planted.css: .x :global(.modal-footer .modal-btn-confirm:disabled) -> --_btn-pad',
    ]);
});
