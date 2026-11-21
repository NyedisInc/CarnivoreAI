import { describe, expect, test } from 'vitest';

import {
    ancestorPaths, companyChoices, companyFolderFor, finalPath, isInside, owningCompany, relativeTo, rootPrefix, slugify, toTreeNodes,
    type CompanyRow, type TreeFolder,
} from './model';

const COMPANIES: CompanyRow[] = [
    { id: 1, name: 'Acme', folder: '/o/Acme' },
    { id: 13, name: 'Globex', parent_id: 1, folder: '/o/Acme/Globex' },
    { id: 5, name: 'Apex', parent_id: 1, folder: '/o/Acme/Apex' },
    { id: 4, name: 'Personal', folder: '/o/Personal' },
    { id: 9, name: 'Scratch' },
];

const folder = (name: string, path: string, children: TreeFolder[] = []): TreeFolder => ({ name, path, project: false, company: null, children });

describe('slugs and paths', () => {
    test('a name becomes a folder name, and an empty one stays empty', () => {
        expect(slugify('Invoice Sync!')).toBe('invoice-sync');
        expect(slugify('  --Dental  Co.--')).toBe('dental-co');
        expect(slugify('!!!')).toBe('');
        expect(finalPath('/o/Acme/Globex', 'Invoice Sync')).toBe('/o/Acme/Globex/invoice-sync');
        expect(finalPath('', 'Invoice Sync')).toBe('');
        expect(finalPath('/o/Acme', '???')).toBe('');
    });

    test('containment is by whole components', () => {
        expect(isInside('/o/Acme', '/o')).toBe(true);
        expect(isInside('/o', '/o')).toBe(true);
        expect(isInside('/oops/Acme', '/o')).toBe(false);
        expect(relativeTo('/o/Acme/Globex', '/o')).toBe('Acme/Globex');
        expect(relativeTo('/elsewhere', '/o')).toBe('/elsewhere');
        expect(rootPrefix('/Users/x/Dev/Org')).toBe('…/Org/');
        expect(ancestorPaths('/o/Acme/Globex', '/o')).toEqual(['/o/Acme', '/o/Acme/Globex']);
        expect(ancestorPaths('/elsewhere', '/o')).toEqual([]);
    });
});

describe('which company owns a folder', () => {
    test('the deepest stored folder wins, and a company with none owns nothing', () => {
        expect(owningCompany('/o/Acme/Globex/payroll', COMPANIES)?.name).toBe('Globex');
        expect(owningCompany('/o/Acme/other', COMPANIES)?.name).toBe('Acme');
        expect(owningCompany('/o/Ventures', COMPANIES)).toBeNull();
    });
});

describe('the company dropdown', () => {
    const self = (n: string): string => `${n} (the parent itself)`;

    test('a parent with companies under it is a group, a lone company a plain option', () => {
        const choices = companyChoices(COMPANIES, self);
        expect(choices).toEqual([
            { group: 'Acme', options: [
                { value: '1', label: 'Acme (the parent itself)' },
                { value: '5', label: 'Acme > Apex' },
                { value: '13', label: 'Acme > Globex' },
            ] },
            { value: '4', label: 'Personal' },
            { value: '9', label: 'Scratch' },
        ]);
    });

    test('a deeper company is labelled with its whole trail, and an orphaned parent id is treated as top level', () => {
        const deep: CompanyRow[] = [...COMPANIES, { id: 20, name: 'Camera', parent_id: 13 }, { id: 21, name: 'Lost', parent_id: 999 }];
        const group = companyChoices(deep, self)[0] as unknown as { options: { label: string }[] };
        expect(group.options.map((o) => o.label)).toContain('Acme > Globex > Camera');
        expect(companyChoices(deep, self).some((c) => 'value' in c && c.label === 'Lost')).toBe(true);
    });
});

describe('the tree filter', () => {
    const TREE = [folder('Acme', '/o/Acme', [folder('Globex', '/o/Acme/Globex', [folder('payroll', '/o/Acme/Globex/payroll')]), folder('Umbrella', '/o/Acme/Umbrella')]), folder('Personal', '/o/Personal')];

    test('no filter keeps everything; leaves have no children key', () => {
        const nodes = toTreeNodes(TREE, '/o', '');
        expect(nodes.map((n) => n.id)).toEqual(['/o/Acme', '/o/Personal']);
        expect(nodes[1]!.children).toBeUndefined();
    });

    test('a match keeps its ancestors, and only the matching branch', () => {
        const nodes = toTreeNodes(TREE, '/o', 'glo');
        expect(nodes.map((n) => n.id)).toEqual(['/o/Acme']);
        expect(nodes[0]!.children!.map((n) => n.id)).toEqual(['/o/Acme/Globex']);
        expect(toTreeNodes(TREE, '/o', 'zzz')).toEqual([]);
    });
});

describe('a new company\'s folder', () => {
    test('typed text is relative to the root unless absolute; blank is the parent folder plus the slug', () => {
        expect(companyFolderFor('Acme/Acme/', null, '/o', 'x')).toBe('/o/Acme/Acme');
        expect(companyFolderFor('/o/Other', null, '/o', 'x')).toBe('/o/Other');
        expect(companyFolderFor('', '/o/Acme', '/o', 'Acme Co')).toBe('/o/Acme/acme-co');
        expect(companyFolderFor('', null, '/o', 'Acme Co')).toBe('/o/acme-co');
        expect(companyFolderFor('', null, '/o', '???')).toBe('');
    });
});
