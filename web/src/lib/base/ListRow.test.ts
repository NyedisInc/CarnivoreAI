/** @vitest-environment jsdom */
import { readFileSync } from 'node:fs';
import { afterEach, describe, expect, test } from 'vitest';
import { createRawSnippet, flushSync, mount, unmount } from 'svelte';

import ListRow from './ListRow.svelte';
import { cssRules, type CssRule } from './css-rules';

const listCss = readFileSync(`${process.cwd()}/src/lib/base/list.css`, 'utf8');
const focusCss = readFileSync(`${process.cwd()}/src/opscenter/focus.css`, 'utf8');

let mounted: Record<string, unknown>[] = [];
afterEach(() => {
    for (const m of mounted) unmount(m);
    mounted = [];
    document.body.innerHTML = '';
});

const html = (markup: string) => createRawSnippet(() => ({ render: () => markup }));

function row(props: Record<string, unknown>): HTMLElement {
    const target = document.createElement('div');
    document.body.append(target);
    mounted.push(mount(ListRow, { target, props }) as Record<string, unknown>);
    flushSync();
    return target.querySelector('.oc-list__row')!;
}

const SIZING = /^(?:(?:min-|max-)?(?:height|block-size|width|inline-size)|padding.*|margin.*|border(?:-(?:top|bottom|left|right|block|inline))?(?:-width)?|font-size|line-height|display|flex-wrap)$/;

function stateSizing(rules: CssRule[]): string[] {
    const state = /\.oc-list__row[^,{]*(?::hover|:focus|\[data-selected\]|\[aria-selected|\[aria-current)/;
    return rules
        .filter((r) => state.test(r.selector))
        .flatMap((r) => Object.keys(r.decls).filter((p) => SIZING.test(p)).map((p) => `${r.selector} { ${p} }`));
}

describe('the row never changes height on hover or focus', () => {
    const rules = cssRules(listCss);

    test('hover, focus and selected rules move only colors and the inset shadow', () => {
        expect(stateSizing(rules)).toEqual([]);
    });

    test('aria-disabled="true" gets a base disabled look (dim token, no pointer action) and drops the pointer flag', () => {
        const rule = cssRules(listCss).find((r) => r.selector === ".oc-list__row[aria-disabled='true']");
        expect(rule?.decls['color']).toBe('var(--oc-text-dim)');
        expect(rule?.decls['pointer-events']).toBe('none');
        expect(rule?.decls['cursor']).toBe('default');
        const root = document.createElement('div');
        document.body.append(root);
        mounted.push(mount(ListRow, { target: root, props: { primary: 'x', onclick: () => {}, 'aria-disabled': 'true' } }) as Record<string, unknown>);
        flushSync();
        expect(root.querySelector('.oc-list__row')!.hasAttribute('data-interactive')).toBe(false);
    });

    test('a row has nothing on hover (Joe (ccsliinc), 2026-10-26): no hover rule, no hover tint', () => {
        expect(rules.filter((r) => r.selector.includes(':hover'))).toEqual([]);
        const elementsCss = readFileSync(`${process.cwd()}/src/lib/base/elements.css`, 'utf8');
        const rowBtn = cssRules(elementsCss).find((r) => r.selector === ":where([data-btn='row'])")!;
        expect(rowBtn.decls['--_btn-fill-hover']).toBe('transparent');
        expect(rowBtn.decls['--_btn-ink-hover']).toBe('var(--_btn-ink)');
        expect(rowBtn.decls['--_btn-edge-hover']).toBe('transparent');
    });

    test('the border the focus rule lights is reserved at rest, and the focus rule only recolors it', () => {
        const base = rules.find((r) => r.selector === '.oc-list__row')!;
        expect(base.decls.border).toMatch(/var\(--oc-border\) solid transparent/);
        expect(base.decls['min-block-size']).toContain('--oc-list-row-h');
        const focus = cssRules(focusCss).filter((r) => r.selector.includes(':focus-visible'));
        expect(focus.length).toBeGreaterThan(0);
        for (const r of focus) expect(Object.keys(r.decls).filter((p) => SIZING.test(p))).toEqual([]);
    });

    test('negative control: a planted hover padding is caught', () => {
        expect(stateSizing(cssRules('.oc-list__row:hover { padding-block: 4px; background: red }'))).toEqual([
            '.oc-list__row:hover { padding-block }',
        ]);
    });

    test('the three densities are the base row tokens', () => {
        const height = (sel: string) => rules.find((r) => r.selector.split(',').map((s) => s.trim()).includes(sel))?.decls['--oc-list-row-h'];
        expect(height(".oc-list__row[data-density='dense']")).toBe('var(--oc-row-h-dense)');
        expect(height(".oc-list__row[data-density='default']")).toBe('var(--oc-row-h)');
        expect(height(".oc-list__row[data-density='roomy']")).toBe('var(--oc-row-h-roomy)');
    });
});

describe('trailing actions', () => {
    const rules = cssRules(listCss);

    test('always shown at rest: no rule sets them transparent or hidden, on any state', () => {
        const mine = rules.filter((r) => r.selector.includes('.oc-list__actions'));
        expect(mine.length).toBeGreaterThan(0);
        for (const r of mine) {
            expect(r.decls.opacity, r.selector).toBeUndefined();
            expect(r.decls.visibility, r.selector).toBeUndefined();
            expect(r.decls.display, r.selector).not.toBe('none');
        }
    });

    test('negative control: a planted hover-only reveal is caught', () => {
        const planted = cssRules('.oc-list__actions { opacity: 0 } .oc-list__row:hover .oc-list__actions { opacity: 1 }');
        expect(planted.filter((r) => r.decls.opacity !== undefined)).toHaveLength(2);
    });

    test('drawn last, in their own cell', () => {
        const el = row({ primary: 'nightly', actions: html('<button type="button">run</button>') });
        expect(el.lastElementChild?.className).toBe('oc-list__actions');
        expect(el.querySelector('.oc-list__actions button')?.textContent).toBe('run');
    });
});

describe('ListRow markup', () => {
    test('parts in the fixed order, strings or snippets', () => {
        const el = row({
            lead: html('<i data-led></i>'),
            primary: 'nightly backup',
            secondary: html('<span>every day at 02:00</span>'),
            meta: '12s',
        });
        expect([...el.children].map((c) => c.className)).toEqual(['oc-list__lead', 'oc-list__main', 'oc-list__meta']);
        expect(el.querySelector('.oc-list__primary')?.textContent).toBe('nightly backup');
        expect(el.querySelector('.oc-list__secondary')?.textContent).toBe('every day at 02:00');
        expect(el.querySelector('.oc-list__meta')?.textContent).toBe('12s');
        expect(el.getAttribute('role')).toBe('listitem');
    });

    test('selected, density, a click target and passed-through attributes', () => {
        const el = row({ primary: 'a', selected: true, density: 'dense', onclick: () => {}, 'data-id': 'x', class: 'mine' });
        expect(el.hasAttribute('data-selected')).toBe(true);
        expect(el.dataset.density).toBe('dense');
        expect(el.hasAttribute('data-interactive')).toBe(true);
        expect(el.dataset.id).toBe('x');
        expect(el.classList.contains('mine')).toBe(true);
        const plain = row({ primary: 'b' });
        expect(plain.hasAttribute('data-selected') || plain.hasAttribute('data-interactive')).toBe(false);
    });

    test('custom cells replace the text parts (a grid row)', () => {
        const el = row({ role: 'row', children: html('<span role="gridcell">a</span>') });
        expect(el.getAttribute('role')).toBe('row');
        expect(el.querySelector('.oc-list__main')).toBeNull();
        expect(el.querySelector('[role="gridcell"]')?.textContent).toBe('a');
    });
});

describe('a wrapping row', () => {
    test('the flag lands as data-wrap and the stylesheet lets the text wrap without touching a state', () => {
        const el = row({ primary: 'a long line of words', wrap: true });
        expect(el.getAttribute('data-wrap')).toBe('true');
        expect(row({ primary: 'x' }).hasAttribute('data-wrap')).toBe(false);
        const rules = cssRules(listCss).filter((r) => r.selector.includes('[data-wrap]'));
        expect(rules.length).toBeGreaterThan(0);
        expect(rules.some((r) => r.decls['white-space'] === 'normal')).toBe(true);
        expect(rules.every((r) => !/:hover|:focus|\[data-selected\]|\[aria-selected/.test(r.selector))).toBe(true);
    });
});
