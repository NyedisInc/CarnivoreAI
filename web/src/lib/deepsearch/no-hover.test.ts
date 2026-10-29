import fs from 'node:fs';
import path from 'node:path';
import { expect, test } from 'vitest';

const read = (rel: string): string => fs.readFileSync(path.resolve(process.cwd(), 'src/lib', rel), 'utf8').replace(/\/\*[\s\S]*?\*\//g, '');
const rules = (css: string): Array<{ sel: string; body: string }> =>
    [...css.matchAll(/([^{}]+)\{([^{}]*)\}/g)].map((m) => ({ sel: m[1]!.trim(), body: m[2]!.trim() }));

test('no hover rule in the search results or sections paints anything but the neutral reset', () => {
    for (const file of ['deepsearch/results.css', 'deepsearch/search-d.css', 'sidebar-shell/search-sections.css']) {
        for (const { sel, body } of rules(read(file))) {
            if (!sel.includes(':hover') || sel.includes('.acm-')) continue;
            expect(body, `${file}: ${sel}`).toMatch(/^background:\s*transparent;(\s*border-color:\s*(var\(--oc-line-panel\)|transparent);?)?$/);
        }
    }
});

test('a result row, a hit and an agent row paint nothing on hover: the mock\'s `.hit` and `.r` have no hover rule, only the agent row\'s drawer hover is put back to rest', () => {
    const results = rules(read('deepsearch/results.css')).concat(rules(read('deepsearch/search-d.css')));
    const hoverOnResults = results.filter((r) => r.sel.includes(':hover') && !r.sel.includes('.acm-')).map((r) => r.sel);
    expect(hoverOnResults, 'no hover rule on a hit, a prompt or a head').toEqual([]);
    const resets = rules(read('sidebar-shell/search-sections.css')).filter((r) => r.sel.includes(':hover')).map((r) => r.sel).join(' | ');
    expect(resets).toContain(".session-sidebar-row:not([data-search-cursor='1']):hover");
    expect(resets).toContain("[data-search-section='agents'] .session-sidebar-row");
});

test('an agent row in a search keeps its own menu key: the session row contract (Joe, 2026-10-22)', () => {
    const css = read('sidebar-shell/search-sections.css');
    const hides = rules(css).filter((r) => r.sel.includes('session-row-menu-trigger') && /display:\s*none|visibility:\s*hidden/.test(r.body));
    expect(hides).toEqual([]);
});

test('an agent row in the search draws no hover border: the drawer row hover border (row-polish.css) is put back to rest', () => {
    const reset = rules(read('sidebar-shell/search-sections.css')).find((r) => r.sel.includes("[data-search-section='agents']") && r.sel.includes(':hover'));
    expect(reset?.body).toMatch(/border-color:\s*transparent/);
    const polish = rules(read('sidebar-shell/row-polish.css')).find((r) => r.sel.includes(':hover') && r.sel.includes('[role="option"]'));
    expect(polish, 'the drawer hover border this reset answers still exists').toBeDefined();
});

test('the names mode draws no CONVERSATIONS section: only the no-match line when no agent matched', () => {
    const src = fs.readFileSync(path.resolve(process.cwd(), 'src/lib/sidebar-shell/SearchConversations.svelte'), 'utf8');
    expect(src).toMatch(/\{#if nothing \|\| c !== null\}/);
});
