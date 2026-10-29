/** @vitest-environment jsdom */
import { describe, expect, it } from 'vitest';
import { withInactiveProjects } from './plan';
import { inactiveProjectIcon, archivedChip } from './row-chips';
import type { ProjectBucket, SidebarRow } from './legacy';

const live: ProjectBucket = { key: 'p:1', label: 'live', rows: [{ name: 'a' } as SidebarRow], isProject: true };

describe('inactive projects', () => {
    it('tick off (nothing known): the buckets come back untouched', () => {
        const buckets = [live];
        expect(withInactiveProjects(buckets, [])).toBe(buckets);
    });

    it('tick on: every known project with no band is added empty, A-Z, after the live ones', () => {
        const out = withInactiveProjects([live], [{ id: '1', name: 'live' }, { id: '7', name: 'zed' }, { id: '4', name: 'alpha' }]);
        expect(out.map((b) => b.key)).toEqual(['p:1', 'p:4', 'p:7']);
        expect(out[1]!.rows).toEqual([]);
    });

    it('the inactive project and archived session marks are icons with an aria-label and a tooltip', () => {
        const proj = inactiveProjectIcon();
        expect(proj.svg).toContain('<svg');
        expect(proj.attrs['aria-label']).toBe('inactive project');
        expect(proj.attrs.title).toBe('inactive project');
        const arch = archivedChip({ archived: true } as unknown as SidebarRow)!;
        expect(arch.svg).toContain('<svg');
        expect(arch.attrs['aria-label']).toBe(arch.attrs.title);
        expect(archivedChip({} as SidebarRow)).toBeNull();
    });
});
