/* nothing at all */
import { describe, expect, it } from 'vitest';
import { ARCHIVED_NAME_PREFIX, archivedLast, archivedRows } from './archived-rows';

const records = [
    { archived_at: '2026-10-01', session_uuid: 'u-old', tmux_name: null, title: 'old talk', project_id: 5, project_name: 'moved' },
    { archived_at: '2026-10-02', session_uuid: 'u-named', tmux_name: 'carnivore_live', title: 'shadowed', project_id: 5 },
    { archived_at: null, session_uuid: 'u-live', tmux_name: 'carnivore_x' },
    { archived_at: '2026-10-03', session_uuid: 'u-old', tmux_name: null, title: 'duplicate' },
];

describe('archivedRows', () => {
    it('adds nothing while the toggle is off', () => {
        expect(archivedRows(records, false, new Set())).toEqual([]);
    });

    it('one row per archived record, keyed by uuid, marked archived and never asleep, a listed name winning', () => {
        const rows = archivedRows(records, true, new Set(['carnivore_live']));
        expect(rows.map((r) => r.name)).toEqual([`${ARCHIVED_NAME_PREFIX}u-old`]);
        expect(rows[0]).toMatchObject({
            archived: true, asleep: false, status: 'archived', session_uuid: 'u-old', label: 'old talk', project_id: 5, project_name: 'moved',
        });
    });

    it('a hostile input yields nothing', () => {
        expect(archivedRows(null as unknown as unknown[], true, new Set())).toEqual([]);
    });
});

describe('archivedRows leaves closed sessions to the closed rows (#1845)', () => {
    it('lists only records with archived_at, never a stopped record that is merely closed', () => {
        const rows = archivedRows([
            { session_uuid: 'c', lifecycle: 'stopped', closed: true, tmux_name: 'carnivore_c' },
            { session_uuid: 'a', archived_at: '2026-10-01', tmux_name: 'carnivore_a' },
        ], true, new Set());
        expect(rows.map((r) => r.name)).toEqual([`${ARCHIVED_NAME_PREFIX}a`]);
        expect(rows[0]?.archived).toBe(true);
    });
});

describe('archivedLast', () => {
    it('returns the same array when nothing is archived', () => {
        const rows = [{ name: 'a' }, { name: 'b' }];
        expect(archivedLast(rows)).toBe(rows);
    });

    it('moves archived rows after the others, each side in its order', () => {
        const rows = [{ name: 'x', archived: true }, { name: 'a' }, { name: 'y', archived: true }, { name: 'b' }];
        expect(archivedLast(rows).map((r) => r.name)).toEqual(['a', 'b', 'x', 'y']);
    });
});
