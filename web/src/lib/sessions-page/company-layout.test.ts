import { describe, expect, it } from 'vitest';
import type { Company } from '../companies';
import type { HistoryProject } from '../projects-shared/history-api';
import type { LensGroup } from './lenses';
import { companyLayout } from './company-layout';
import { COMPANY_GROUP_PREFIX } from './company-layout';
import { storeFolds, storedFold } from './folds';

const t = (key: string, p?: Record<string, unknown> | null): string => `${key}:${JSON.stringify(p ?? {})}`;
const co = (id: number, name: string): Company => ({ id, name, project_count: 0 });
const proj = (id: number, name: string, company_id: number | null): HistoryProject => ({ id, name, root: null, description: null, archived_at: null, last_opened_at: null, created_at: null, default_theme: null, company_id });
const grp = (id: number, name: string, company_id: number | null, remote = false): LensGroup => ({
    key: `project:${id}`, label: name, bits: [], measure: '', count: 1, live: 1, project: proj(id, name, company_id), provider: null,
    rows: remote ? ([{ computer: 'other mac' }] as unknown as LensGroup['rows']) : [],
});

describe('companyLayout', () => {
    const companies = [co(1, 'acme'), co(2, 'zeta'), co(3, 'empty co')];
    const groups = [grp(10, 'p-loose', null), grp(11, 'p-zeta', 2), grp(12, 'p-acme', 1), grp(13, 'p-peer', 1, true), grp(14, 'p-gone-co', 99)];

    it('puts each company above its projects, A to Z, and the uncompanied projects after', () => {
        const l = companyLayout(groups, companies, '', true, t);
        expect(l.sections.map((s) => s.head.label)).toEqual(['acme', 'zeta', 'empty co']);
        expect(l.sections[0]?.head.key).toBe(`${COMPANY_GROUP_PREFIX}1`);
        expect(l.sections[0]?.groups.map((g) => g.label)).toEqual(['p-acme']);
        expect(l.groups.map((g) => g.label)).toEqual(['p-acme', 'p-zeta', 'p-loose', 'p-peer', 'p-gone-co']);
    });

    it('never files a paired computer project under this computer company', () => {
        const l = companyLayout(groups, companies, '', true, t);
        expect(l.loose.map((g) => g.label)).toContain('p-peer');
    });

    it('narrows: an empty company shows only when its name matches the find, and not while a filter is set', () => {
        expect(companyLayout([], companies, 'empty', true, t).sections.map((s) => s.head.label)).toEqual(['empty co']);
        expect(companyLayout([], companies, 'nomatch', true, t).sections).toEqual([]);
        expect(companyLayout([], companies, '', false, t).sections).toEqual([]);
    });
});

describe('company folds', () => {
    it('remembers a company fold as c:<id> and an unfold as the key gone, never c:<id>:open', () => {
        storeFolds([['c:7', true]]);
        expect(storedFold('c:7')).toBe(true);
        storeFolds([['c:7', false]]);
        expect(storedFold('c:7')).toBeNull();
    });
});
