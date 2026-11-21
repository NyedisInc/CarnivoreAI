import { describe, expect, it } from 'vitest';
import { addRows } from './asleep';
import { addClosedRows } from './closed';
import { stamp, type SessionRecord } from './row-identity';

const NAME = 'carnivore_Carnivore';
const asleep = (uuid: string) => ({ asleep: true, archived_at: null, session_uuid: uuid, tmux_name: NAME, title: uuid });
const closed = (uuid: string) => ({ closed: true, session_uuid: uuid, tmux_name: NAME, title: uuid });

describe('rows sharing a tmux name (#2979)', () => {
    it('every asleep record gets a row; the first keeps the plain name, the rest take asleep:<uuid>', () => {
        const rows: Array<Record<string, unknown>> = [];
        expect(addRows(rows, [asleep('u1'), asleep('u2'), asleep('u3')])).toBe(3);
        expect(rows.map((r) => r.session_uuid)).toEqual(['u1', 'u2', 'u3']);
        expect(rows.map((r) => r.name)).toEqual([NAME, 'asleep:u2', 'asleep:u3']);
        expect(new Set(rows.map((r) => r.name)).size).toBe(3);
    });

    it('every closed record gets a row, beside asleep rows with the same name', () => {
        const rows: Array<Record<string, unknown>> = [];
        addRows(rows, [asleep('u1')]);
        expect(addClosedRows(rows, [closed('u2'), closed('u3'), closed('u3')])).toBe(2);
        expect(rows.map((r) => r.session_uuid)).toEqual(['u1', 'u2', 'u3']);
        expect(new Set(rows.map((r) => r.name)).size).toBe(3);
        expect(rows[1]).toMatchObject({ closed: true, name: 'closed:u2' });
    });

    it('a live row keeps its name and gets no twin; a different session with the same name still shows', () => {
        const live = { name: NAME, session_uuid: 'u-live', status: 'working' };
        const rows: Array<Record<string, unknown>> = [live];
        addRows(rows, [asleep('u-live'), asleep('u-old')]);
        addClosedRows(rows, [closed('u-live'), closed('u-gone')]);
        expect(rows[0]).toBe(live);
        expect(rows.map((r) => r.session_uuid)).toEqual(['u-live', 'u-old', 'u-gone']);
        expect(rows.filter((r) => r.name === NAME)).toHaveLength(1);
    });

    it('a live row with no uuid yet (external tmux) still wins its name, never guessed away', () => {
        const rows: Array<Record<string, unknown>> = [{ name: NAME, status: 'working' }];
        expect(addRows(rows, [asleep('u1')])).toBe(0);
        expect(addClosedRows(rows, [closed('u2')])).toBe(0);
    });

    it('the identity stamp keeps each twin on its own uuid', () => {
        const rows: Array<Record<string, unknown>> = [];
        addRows(rows, [asleep('u1'), asleep('u2')]);
        stamp(rows, [asleep('u1'), asleep('u2')] satisfies SessionRecord[]);
        expect(rows.map((r) => r.session_uuid)).toEqual(['u1', 'u2']);
    });

    it('each row carries its own real tmux name and its own work stamp, never a twin\'s (#2979)', () => {
        const rows: Array<Record<string, unknown>> = [];
        addRows(rows, [
            { ...asleep('u1'), last_work_at: '2026-11-02T00:00:00Z' },
            { ...asleep('u2'), last_work_at: '2026-11-01T00:00:00Z' },
        ]);
        expect(rows.map((r) => r.tmux_name)).toEqual([NAME, NAME]);
        expect(rows.map((r) => r.last_work_at)).toEqual(['2026-11-02T00:00:00Z', '2026-11-01T00:00:00Z']);
        const closedRows: Array<Record<string, unknown>> = [];
        addClosedRows(closedRows, [{ ...closed('u3'), last_work_at: '2026-10-01T00:00:00Z' }, { closed: true, session_uuid: 'u4' }]);
        expect(closedRows.map((r) => [r.tmux_name, r.last_work_at])).toEqual([[NAME, '2026-10-01T00:00:00Z'], [null, null]]);
    });
});
