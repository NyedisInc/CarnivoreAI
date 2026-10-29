import { describe, expect, it } from 'vitest';
import { addClosedRows, CLOSED_NAME_PREFIX, isClosedRow } from './closed';
import { filterAwakeSleeping } from './bucketing';
import { rowCounts } from './agent-counts';

const closedRec = { closed: true, asleep: false, lifecycle: 'stopped', session_uuid: 'u-c', tmux_name: 'carnivore_c', title: 'was open', project_id: 5, project_name: 'moved', agent_family: 'claude' };

describe('addClosedRows', () => {
    it('adds one closed row per closed record, marked closed and neither asleep nor archived', () => {
        const rows: Array<Record<string, unknown>> = [];
        expect(addClosedRows(rows, [closedRec])).toBe(1);
        expect(rows[0]).toMatchObject({ name: 'carnivore_c', closed: true, asleep: false, archived: false, status: 'closed', session_uuid: 'u-c', session_id: null, project_id: 5 });
        expect(isClosedRow(rows[0])).toBe(true);
    });

    it('skips records the server did not call closed: asleep, archived, running', () => {
        const rows: Array<Record<string, unknown>> = [];
        addClosedRows(rows, [
            { ...closedRec, session_uuid: 'a', closed: false, asleep: true },
            { ...closedRec, session_uuid: 'b', closed: false, archived_at: '2026-10-01' },
            { ...closedRec, session_uuid: 'c', closed: false, lifecycle: 'running' },
        ]);
        expect(rows).toEqual([]);
    });

    it('a live row holding the name wins; a record with no tmux name gets a closed: key', () => {
        const rows: Array<Record<string, unknown>> = [{ name: 'carnivore_c' }];
        expect(addClosedRows(rows, [closedRec, { ...closedRec, session_uuid: 'u-n', tmux_name: null }])).toBe(1);
        expect(rows.map((r) => r.name)).toEqual(['carnivore_c', `${CLOSED_NAME_PREFIX}u-n`]);
    });

    it('lists a record once even when it arrives twice', () => {
        const rows: Array<Record<string, unknown>> = [];
        expect(addClosedRows(rows, [closedRec, { ...closedRec, tmux_name: 'carnivore_other' }])).toBe(1);
    });
});

describe('a closed row among the others', () => {
    const closed = { name: 'carnivore_c', closed: true, status: 'closed', agent_family: 'claude' };
    const live = { name: 'carnivore_l', status: 'idle', agent_family: 'claude' };
    const nap = { name: 'carnivore_n', status: 'asleep', asleep: true, agent_family: 'claude' };

    it('passes both awake/sleeping filters, which only drop awake and asleep sessions', () => {
        expect(filterAwakeSleeping([live, nap, closed] as never, true, false).map((r) => r.name)).toEqual(['carnivore_l', 'carnivore_c']);
        expect(filterAwakeSleeping([live, nap, closed] as never, false, true).map((r) => r.name)).toEqual(['carnivore_n', 'carnivore_c']);
    });

    it('is in no count', () => {
        expect(rowCounts(closed as never)).toBeNull();
        expect(rowCounts(live as never)).not.toBeNull();
    });
});
