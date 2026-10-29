/** @vitest-environment jsdom */
import { describe, expect, it, vi } from 'vitest';
import * as Store from '../drawer/store';
import { buildListPlan } from './plan';
import type { LegacyDrawer, SidebarRow } from './legacy';

vi.mock('./company-source.svelte', () => ({
    companySource: () => ({ companies: [{ id: 7, name: 'acme' }], companyOf: (id: string) => (String(id) === '1' ? 7 : null) }),
    watchCompanies: () => {},
}));

const legacy = {
    groups: {},
    projectHeader: { ledHtml: () => '', iconHtml: (n: string | null) => (n ? `<i ${n}>` : ''), iconForBand: () => null },
} as unknown as LegacyDrawer;

describe('company heading icons', () => {
    it('a real company wears the building, the orphaned heading keeps folder-tree', () => {
        localStorage.clear();
        Store.load();
        const rows: SidebarRow[] = [{ name: 'a', project_id: 1, project_name: 'one' }, { name: 'b', project_id: 2, project_name: 'two' }];
        const plan = buildListPlan(legacy, { rows, density: 'compact', listing: { ok: true }, missing: [], arrangement: null, opts: {} })!;
        const icon = (key: string): string | undefined => {
            const p = plan.parts.find((x) => x.key === key);
            return p?.type === 'company' ? p.heading.iconHtml : undefined;
        };
        expect(icon('c:7')).toContain('building');
        expect(icon('c:orphaned')).toContain('folder-tree');
    });
});
