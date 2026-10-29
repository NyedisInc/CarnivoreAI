import { describe, expect, it } from 'vitest';
import { indexLeaders, insigniaSvg, placeLeaders, projectLeaderFirst } from './leaders';
import type { SidebarRow } from './legacy';

const roster = [
    { id: 1, rank: 'alpha', display_name: 'Alpha', session_row_id: 10, session_uuid: 'u-alpha' },
    { id: 2, rank: 'company', display_name: 'Acme HQ', session_row_id: 11, session_uuid: 'u-acme', company_id: 7 },
    { id: 3, rank: 'project', display_name: 'Plain agent', session_row_id: 12, session_uuid: 'u-plain' },
    { id: 4, rank: 'feature', display_name: 'Feat', session_row_id: 13, session_uuid: 'u-feat' },
];
const row = (name: string, id: number | null, uuid?: string): SidebarRow => ({ name, session_row_id: id, session_uuid: uuid });

describe('swarm leaders in the agents drawer', () => {
    const idx = indexLeaders(roster);
    const rows = [row('t1', 20), row('plain-task', 21), row('plain', 12), row('acme', 11), row('feat', 13), row('alpha', 10), row('rowless', null, 'u-plain')];

    it('joins on the session row id or uuid, never the tmux name, and ignores feature agents', () => {
        expect(idx.of(row('cloude_alpha_renamed', 10))?.rank).toBe('alpha');
        expect(idx.of(row('x', null, 'u-acme'))?.rank).toBe('company');
        expect(idx.of(row('alpha', 99))).toBeNull();
        expect(idx.of(row('feat', 13))).toBeNull();
    });

    it('puts Alpha on top, a company agent under its company, a project agent first in its project', () => {
        const placed = placeLeaders(rows, idx);
        expect(placed.alpha?.name).toBe('alpha');
        expect(placed.companies.get(7)?.name).toBe('acme');
        expect(placed.rest.map((r) => r.name)).toEqual(['t1', 'plain-task', 'plain', 'feat', 'rowless']);
        expect(projectLeaderFirst(placed.rest.slice(0, 3), idx).map((r) => r.name)).toEqual(['plain', 't1', 'plain-task']);
    });

    it('an empty roster places nothing and reorders nothing', () => {
        const none = indexLeaders([]);
        const placed = placeLeaders(rows, none);
        expect(placed.alpha).toBeNull();
        expect(placed.rest).toHaveLength(rows.length);
        expect(projectLeaderFirst(rows, none)).toEqual(rows);
    });

    it('draws one chevron, two chevrons and a star', () => {
        expect(insigniaSvg('project').match(/<path/g)).toHaveLength(1);
        expect(insigniaSvg('company').match(/<path/g)).toHaveLength(2);
        expect(insigniaSvg('alpha')).toContain('Z');
    });
});
