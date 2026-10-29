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

    it('paints a band heading muted grey with a right-hand hairline, and steps every body in by the one tree step', () => {
        const band = css('session-sidebar-band-structure.css');
        const colour = ruleBody(band, BAND + ':not(:hover, :focus-visible)');
        expect(colour).toMatch(/color:\s*var\(--oc-text-muted\)/);
        expect(colour).not.toMatch(/--oc-orange|--band-hue/);
        const rule = ruleBody(band, BAND + '::after');
        expect(rule).toMatch(/flex:\s*1 1 auto/);
        expect(rule).toMatch(/border-top:\s*1px solid var\(--sidebar-divider\)/);
        expect(band).toMatch(/--sidebar-tree-step:\s*var\(--oc-space-2\);/);
        expect(ruleBody(band, '.session-sidebar-group > .session-sidebar-group__body,\n.session-sidebar-layout__members')).toMatch(/padding-inline-start:\s*var\(--sidebar-tree-step\)/);
        expect(css('session-sidebar-colours.css')).not.toMatch(/\[data-group="pinned"\][^{]*>\s*\.session-sidebar-group__headerrow > \.session-sidebar-group__header/);
    });
});
