/** @vitest-environment jsdom */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { drawList, loadLegacyDrawer, resetDrawer } from './legacy-fixture';
import * as Store from '../drawer/store';
import { isFoldKey } from '../drawer/store-keys';

vi.mock('./company-source.svelte', () => ({
    companySource: () => ({ companies: [{ id: 7, name: 'acme' }], companyOf: (id: string) => (String(id) === '1' ? 7 : null) }),
    watchCompanies: () => {},
}));

const BAND = '.session-sidebar-group > .session-sidebar-group__headerrow:is([data-band-kind="reserved"], [data-band-kind="group"]) > .session-sidebar-group__header';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../../..');
const css = (name: string): string => fs.readFileSync(path.join(ROOT, 'client', 'css', name), 'utf8');

function ruleBody(text: string, sel: string): string {
    const at = text.indexOf(`${sel} {`);
    expect(at, `rule ${sel}`).toBeGreaterThan(-1);
    return text.slice(at, text.indexOf('}', at));
}

const rows = [
    { name: 'cloude_a', created_by_cloude: true, status: 'working', unread: false, is_pinned: true, project_id: 1, project_name: 'one' },
    { name: 'cloude_b', created_by_cloude: true, status: 'idle', unread: false, is_pinned: false, project_id: 1, project_name: 'one' },
    { name: 'cloude_c', created_by_cloude: true, status: 'idle', unread: false, is_pinned: false, project_id: 2, project_name: 'two' },
];

function draw(collapsed: string[]): HTMLElement {
    Store.save(['cloude_a'], rows.map((r) => r.name), collapsed);
    drawList(rows);
    return document.getElementById('session-sidebar-list')!;
}

beforeAll(() => { loadLegacyDrawer(); });
beforeEach(() => { resetDrawer(); });

describe('agents tab grouping headings', () => {
    it('draws PINNED and COMPANIES as band headings, the companies inside COMPANIES, and folds it', () => {
        const list = draw([]);
        const companies = list.querySelector('.session-sidebar-companies')!;
        expect(companies).toBeTruthy();
        const head = companies.querySelector(':scope > .session-sidebar-group__headerrow')!;
        const isBand = (el: Element | null): boolean => !!el && el.querySelector(':scope > .session-sidebar-group__headerrow > .session-sidebar-group__header')!.matches(BAND);
        expect(isBand(companies)).toBe(true);
        expect(head.querySelector('.session-sidebar-group__label')!.textContent).toBe('companies');
        expect(head.querySelector('.session-sidebar-group__icon')).toBeTruthy();
        const companyIcon = list.querySelector('[data-company="c:7"] .session-sidebar-group__icon')!;
        expect(head.querySelector('.session-sidebar-group__icon')!.innerHTML).toBe(companyIcon.innerHTML);
        const body = companies.querySelector(':scope > .session-sidebar-group__body')!;
        expect(body.querySelector('.session-sidebar-company[data-company="c:7"]')).toBeTruthy();
        expect(isBand(list.querySelector('[data-group="pinned"]'))).toBe(true);
        expect(isBand(list.querySelector('[data-company="c:7"]'))).toBe(false);
        const orphaned = list.querySelector('[data-company="c:orphaned"]');
        expect(orphaned, 'setup: the orphaned-projects heading is drawn').toBeTruthy();
        expect(isBand(orphaned)).toBe(true);
        expect(isBand(list.querySelector('[data-group="p:1"]'))).toBe(false);

        expect(isFoldKey('companies')).toBe(true);
        const folded = draw(['companies']);
        expect(folded.querySelector('.session-sidebar-companies [aria-expanded="false"]')).toBeTruthy();
        expect(folded.querySelector('.session-sidebar-company')).toBeNull();
    });

    it('paints sticky uppercase muted band headings, section-only carets, single guide lines, and no project sub-lines', () => {
        const band = css('session-sidebar-band-structure.css');
        const groups = css('session-sidebar-groups.css');
        const layouts = css('session-sidebar-layouts.css');
        const colour = ruleBody(band, BAND + ':not(:hover, :focus-visible)');
        expect(colour).toMatch(/color:\s*var\(--oc-text-muted\)/);
        expect(colour).not.toMatch(/--oc-orange|--band-hue/);
        expect(band).toMatch(/position:\s*sticky/);
        expect(band).toMatch(/border-inline-start:\s*var\(--oc-border\) solid color-mix\(in oklab, var\(--sb-tint, var\(--oc-text-muted\)\) 50%, transparent\)/);
        expect(band).toMatch(/--sidebar-tree-step:\s*var\(--oc-space-2\);/);
        expect(ruleBody(band, '.session-sidebar-group > .session-sidebar-group__body,\n.session-sidebar-layout__members')).toMatch(/padding-inline-start:\s*var\(--sidebar-tree-step\)/);
        expect(ruleBody(groups, '.session-sidebar-group__headerrow .session-sidebar-group__gutter')).toMatch(/display:\s*none/);
        expect(ruleBody(groups, '.session-sidebar-group[data-section] > .session-sidebar-group__headerrow[data-band-kind="reserved"] .session-sidebar-group__gutter')).toMatch(/display:\s*flex/);
        expect(ruleBody(layouts, '.session-sidebar-layout__toggle')).toMatch(/display:\s*none/);
        const colours = css('session-sidebar-colours.css');
        expect(colours).not.toMatch(/\[data-group="pinned"\][^{]*>\s*\.session-sidebar-group__headerrow > \.session-sidebar-group__header/);
        expect(colours).not.toMatch(/\[data-group\^="p:"\][^{]*>\s*\.session-sidebar-group__body:has\(> \*\)/);
        expect(ruleBody(colours, '.session-sidebar-layout__members')).toMatch(/border-inline-start:\s*var\(--oc-border\) solid color-mix\(in oklab, var\(--row-hue\) 50%, transparent\)/);
        expect(colours).toContain('.session-sidebar-row[data-layout-colour="coral"] + .session-sidebar-layout__members');
        expect(colours).toContain('.session-sidebar-row[data-kind="layout"][data-layout-colour] .session-sidebar-row-provider');
        expect(ruleBody(colours, ':is(.session-sidebar-group[data-section="groups"], .session-sidebar-group[data-group="pinned"]) > .session-sidebar-group__body > .session-sidebar-group[data-group^="g:"] > .session-sidebar-group__body:has(> *)')).toMatch(/border-inline-start:\s*var\(--oc-border\) solid color-mix\(in oklab, var\(--band-hue\) 50%, transparent\)/);
    });
});
