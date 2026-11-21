/** @vitest-environment jsdom */
import { afterEach, describe, expect, test } from 'vitest';

import { openModal } from '../modal';
import { createI18n } from '../../../../client/js/i18n/runtime.js';
import NewProjectModal from './NewProjectModal.svelte';
import type { NewProjectApi } from './api';
import type { CompanyRow, FolderTree, Finding, Verdict } from './model';
import type { NewProjectChoice } from '../launchpad/modal-types';

if (typeof CSS === 'undefined') (globalThis as { CSS?: unknown }).CSS = {};
if (!CSS.escape) CSS.escape = (v: string): string => v.replace(/[^\w-]/g, (c) => `\\${c}`);

const i18n = createI18n({ locale: 'en' }) as { t(key: string, params?: Record<string, unknown> | null): string };
const t = (key: string, params?: Record<string, unknown> | null): string => i18n.t(key, params);

const ROOT = '/o';
const COMPANIES: CompanyRow[] = [
    { id: 1, name: 'Acme', folder: '/o/Acme' },
    { id: 13, name: 'Globex', parent_id: 1, folder: '/o/Acme/Globex' },
    { id: 4, name: 'Personal', folder: '/o/Personal' },
];
const folder = (name: string, path: string, children: FolderTree['nodes'] = [], extra: Partial<FolderTree['nodes'][number]> = {}) =>
    ({ name, path, project: false, company: null, children, ...extra });
const TREE: FolderTree = {
    root: ROOT,
    truncated: false,
    nodes: [
        folder('Acme', '/o/Acme', [
            folder('Globex', '/o/Acme/Globex', [folder('payroll', '/o/Acme/Globex/payroll', [], { project: true })], { company: { id: 13, name: 'Globex' } }),
        ], { company: { id: 1, name: 'Acme' } }),
        folder('Personal', '/o/Personal', [], { company: { id: 4, name: 'Personal' } }),
    ],
};

function fakeApi(findings: Finding[] = [{ level: 'ok', code: 'clean', params: {} }]): { api: NewProjectApi; checks: Array<[string, number | null]>; created: Array<[string, number | null, string | null]> } {
    const checks: Array<[string, number | null]> = [];
    const created: Array<[string, number | null, string | null]> = [];
    const api: NewProjectApi = {
        loadCompanies: async () => COMPANIES,
        loadTree: async () => TREE,
        check: async (path, companyId): Promise<Verdict> => {
            checks.push([path, companyId]);
            return { ok: !findings.some((f) => f.level === 'block'), path, findings };
        },
        createCompany: async (name, parentId, folderPath) => {
            created.push([name, parentId, folderPath]);
            return { id: 99, name, parent_id: parentId, folder: folderPath };
        },
    };
    return { api, checks, created };
}

async function settle(ms = 0): Promise<void> {
    for (let i = 0; i < 8; i += 1) await Promise.resolve();
    await new Promise((r) => setTimeout(r, ms));
    for (let i = 0; i < 8; i += 1) await Promise.resolve();
}

function show(api: NewProjectApi, defaultName = ''): Promise<NewProjectChoice | null> {
    return openModal<NewProjectChoice, Record<string, unknown>>(NewProjectModal as never, {
        title: 'new claude project', confirmLabel: 'create project', defaultName, api, t,
    });
}

const q = <T extends Element>(sel: string): T => document.querySelector(sel) as T;
function setValue(el: HTMLInputElement | HTMLSelectElement, value: string): void {
    el.value = value;
    el.dispatchEvent(new Event(el instanceof HTMLSelectElement ? 'change' : 'input', { bubbles: true }));
}
const confirmBtn = (): HTMLButtonElement => q<HTMLButtonElement>('#new-project-confirm');
const rows = (): string[] => [...document.querySelectorAll('[data-tree-item]')].map((el) => (el as HTMLElement).dataset.treeItem!);
const lines = (): string => q('.oc-lands').textContent ?? '';

afterEach(() => {
    document.body.innerHTML = '';
});

describe('the company dropdown', () => {
    test('groups a parent with its companies, starts unchosen, and ends with "+ new company..."', async () => {
        const { api } = fakeApi();
        void show(api);
        await settle();
        const select = q<HTMLSelectElement>('#new-project-company');
        expect(select.value).toBe('');
        const group = select.querySelector('optgroup')!;
        expect(group.label).toBe('Acme');
        expect([...group.querySelectorAll('option')].map((o) => o.textContent)).toEqual(['Acme (the parent itself)', 'Acme > Globex']);
        const all = [...select.querySelectorAll('option')];
        expect(all[all.length - 1]!.textContent).toBe('+ new company...');
        expect(confirmBtn().disabled).toBe(true);
    });
});

describe('choosing a company opens the tree at its folder', () => {
    test('the tree preselects <company folder>/<slug> and the check asks about exactly that', async () => {
        const { api, checks } = fakeApi();
        const answer = show(api, 'Invoice Sync');
        await settle();
        setValue(q('#new-project-company'), '13');
        await settle(200);

        expect(rows()).toContain('/o/Acme/Globex/payroll');
        expect(q('[data-tree-item="/o/Acme/Globex"]').getAttribute('aria-selected')).toBe('true');
        expect(q('[data-new-project-path]').textContent!.trim()).toBe('…/o/Acme/Globex/invoice-sync');
        expect(checks.at(-1)).toEqual(['/o/Acme/Globex/invoice-sync', 13]);
        expect(lines()).toContain('inside org, not inside another project');
        expect(confirmBtn().disabled).toBe(false);

        confirmBtn().click();
        expect(await answer).toEqual({ name: 'Invoice Sync', folder: '/o/Acme/Globex/invoice-sync', companyId: 13 });
    });

    test('picking a folder owned by another company moves the company to it, and the tags show projects and companies', async () => {
        const { api } = fakeApi();
        void show(api, 'Thing');
        await settle();
        setValue(q('#new-project-company'), '13');
        await settle(200);
        (q('[data-tree-item="/o/Personal"]') as HTMLElement).click();
        await settle(200);
        expect(q<HTMLSelectElement>('#new-project-company').value).toBe('4');
        expect(q('[data-tree-item="/o/Acme/Globex/payroll"]').textContent).toContain('project');
        expect(q('[data-tree-item="/o/Personal"]').textContent).toContain('Personal');
    });

    test('a blocked folder keeps the button off and says why', async () => {
        const { api } = fakeApi([{ level: 'block', code: 'scratch', params: {} }]);
        void show(api, 'Thing');
        await settle();
        setValue(q('#new-project-company'), '13');
        await settle(200);
        expect(lines()).toContain('scratch or temp folder');
        expect(confirmBtn().disabled).toBe(true);
    });

    test('the filter narrows the tree to what matches', async () => {
        const { api } = fakeApi();
        void show(api);
        await settle();
        setValue(q('#new-project-find'), 'pay');
        await settle();
        expect(rows()).toEqual(['/o/Acme', '/o/Acme/Globex', '/o/Acme/Globex/payroll']);
    });
});

describe('"+ new company..." opens the inline box', () => {
    test('the box creates the company through the route, chooses it, and the form answers with its id', async () => {
        const { api, created } = fakeApi();
        const answer = show(api, 'Invoice Sync');
        await settle();
        setValue(q('#new-project-company'), '__new__');
        await settle();
        expect(q('[data-new-company]')).not.toBeNull();

        setValue(q('#new-company-name'), 'Northfield Dental');
        setValue(q('#new-company-parent'), '1');
        await settle();
        expect(q('#new-company-folder-help').textContent).toContain('Acme/northfield-dental/');
        q<HTMLButtonElement>('#new-company-create').click();
        await settle(200);

        expect(created).toEqual([['Northfield Dental', 1, '/o/Acme/northfield-dental']]);
        expect(q('[data-new-company]')).toBeNull();
        expect(q<HTMLSelectElement>('#new-project-company').value).toBe('99');
        expect(q('[data-tree-item="/o/Acme/Globex"]')).not.toBeNull();
        expect(confirmBtn().disabled).toBe(false);
        confirmBtn().click();
        expect((await answer)?.companyId).toBe(99);
    });

    test('a folder typed outside the root is refused on the box and nothing is created', async () => {
        const { api, created } = fakeApi();
        void show(api, 'Thing');
        await settle();
        setValue(q('#new-project-company'), '__new__');
        await settle();
        setValue(q('#new-company-name'), 'Acme');
        setValue(q('#new-company-folder'), '/elsewhere/acme');
        await settle();
        q<HTMLButtonElement>('#new-company-create').click();
        await settle();
        expect(created).toEqual([]);
        expect(q('#new-company-folder-error').textContent).toContain('outside');
    });

    test('cancelling the box goes back to an unchosen company', async () => {
        const { api } = fakeApi();
        void show(api);
        await settle();
        setValue(q('#new-project-company'), '__new__');
        await settle();
        q<HTMLButtonElement>('#new-company-cancel').click();
        await settle();
        expect(q('[data-new-company]')).toBeNull();
        expect(q<HTMLSelectElement>('#new-project-company').value).toBe('');
    });
});

describe('the name is refused, never rewritten', () => {
    test('an illegal name shows its sentence and keeps create off', async () => {
        const { api } = fakeApi();
        void show(api, 'a/b');
        await settle();
        setValue(q('#new-project-company'), '13');
        await settle(200);
        expect(document.body.textContent).toContain("a project name cannot contain '/'");
        expect(confirmBtn().disabled).toBe(true);
    });
});
