import { describe, expect, it } from 'vitest';
import { companyBuckets, sortProjectsAlpha, COMPANY_ORPHANED_KEY, type ProjectBucket } from './bucketing';
import { isBandOrderKey, isFoldKey } from './store-keys';

const proj = (id: number, label: string): ProjectBucket => ({ key: `p:${id}`, label, rows: [], isProject: true });
const rogue: ProjectBucket = { key: 'rogue', label: 'rogue agents', rows: [], isProject: false };

describe('companyBuckets', () => {
    const companies = [{ id: 2, name: 'zeta' }, { id: 1, name: 'Acme' }, { id: 3, name: 'empty co' }];
    const filing: Record<string, number | null> = { '10': 1, '11': 2, '12': null, '13': 99 };
    const companyOf = (id: string): number | null => filing[id] ?? null;

    it('sorts companies A-Z case-insensitively and sorts projects A-Z inside each', () => {
        const out = companyBuckets([proj(10, 'a'), proj(11, 'b'), proj(12, 'c'), proj(13, 'd'), rogue], companies, companyOf);
        expect(out.companies.map((c) => c.key)).toEqual(['c:1', 'c:3', 'c:2', COMPANY_ORPHANED_KEY]);
        expect(out.companies[0]!.projects.map((p) => p.key)).toEqual(['p:10']);
    });

    it('keeps an empty company, and files no company and an unknown company under orphaned, last', () => {
        const out = companyBuckets([proj(10, 'a'), proj(12, 'c'), proj(13, 'd')], companies, companyOf);
        expect(out.companies.find((c) => c.key === 'c:3')!.projects).toEqual([]);
        const orphaned = out.companies[out.companies.length - 1]!;
        expect(orphaned.key).toBe(COMPANY_ORPHANED_KEY);
        expect(orphaned.companyId).toBeNull();
        expect(orphaned.projects.map((p) => p.key)).toEqual(['p:12', 'p:13']);
    });

    it('draws no orphaned bucket when every project is filed, and hands rogue back apart', () => {
        const out = companyBuckets([proj(10, 'a'), rogue], companies, companyOf);
        expect(out.companies.some((c) => c.key === COMPANY_ORPHANED_KEY)).toBe(false);
        expect(out.rogue).toBe(rogue);
        expect(out.companies.every((c) => !c.projects.includes(rogue))).toBe(true);
    });

    it('with zero companies every project is orphaned', () => {
        const out = companyBuckets([proj(10, 'a')], [], companyOf);
        expect(out.companies.map((c) => c.key)).toEqual([COMPANY_ORPHANED_KEY]);
    });
});

describe('project order (Alex (Example-owner), 2026-10-18)', () => {
    it('sorts case-insensitively with natural numbers', () => {
        const out = sortProjectsAlpha(['zeta', 'Alpha', 'beta', 'p10', 'p2'].map((l, i) => proj(i, l)));
        expect(out.map((b) => b.label)).toEqual(['Alpha', 'beta', 'p2', 'p10', 'zeta']);
    });
    it('sorts inside a company and inside orphaned projects', () => {
        const filing: Record<string, number | null> = { '1': 1, '2': 1, '3': null, '4': null, '5': null };
        const labels = ['zeta', 'Alpha', 'mango', 'Cherry', 'apple'];
        const out = companyBuckets(labels.map((l, i) => proj(i + 1, l)), [{ id: 1, name: 'Co' }], (id) => filing[id] ?? null);
        expect(out.companies[0]!.projects.map((p) => p.label)).toEqual(['Alpha', 'zeta']);
        expect(out.companies[1]!.projects.map((p) => p.label)).toEqual(['apple', 'Cherry', 'mango']);
    });
});

describe('company fold keys', () => {
    it('c:<id> and c:orphaned fold, other c: shapes do not, and none is a band order key', () => {
        expect(isFoldKey('c:7')).toBe(true);
        expect(isFoldKey('c:orphaned')).toBe(true);
        expect(isFoldKey('c:')).toBe(false);
        expect(isFoldKey('c:x')).toBe(false);
        expect(isBandOrderKey('c:7')).toBe(false);
    });
});
