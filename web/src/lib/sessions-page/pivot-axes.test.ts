import { describe, expect, test } from 'vitest';
import { buildPivot, type PivotContext } from './pivot-axes';
import { rowsFromGroups } from './filters';
import { group, session } from '../projects-shared/test-fixtures';

const local = (y: number, m: number, d: number, h: number): string => new Date(y, m, d, h, 30).toISOString();

const NOW = new Date(2026, 9, 14, 12, 0).getTime();

const ctx: PivotContext = {
    t: (key) => key,
    now: NOW,
    sig: { live: () => undefined, asleepUnread: () => false },
    usage: null,
    conversations: {},
    noCompany: 'no company',
    thisComputer: 'this computer',
};

const project = (company: string | null) => ({ id: 1, name: 'p', company_name: company }) as never;

describe('pivot company x weekday', () => {
    const rows = rowsFromGroups(
        [
            group({ name: 'acme-app', key: 'a', project: project('Acme'), sessions: [
                session({ session_uuid: 'mon', title: 'mon', state: 'asleep', last_work_at: local(2026, 9, 12, 23), last_activity_at: local(2026, 9, 14, 8) }),
                session({ session_uuid: 'fri', title: 'fri', state: 'asleep', last_work_at: null, last_activity_at: local(2026, 9, 9, 0) }),
            ] }),
            group({ name: 'solo', key: 'b', project: project(null), sessions: [session({ session_uuid: 'sun', title: 'sun', state: 'asleep', last_work_at: local(2026, 9, 11, 0) })] }),
        ],
        [],
        'no project',
    );
    const model = buildPivot(rows, 'company', 'weekday', ctx);
    const at = (row: string, col: string): string[] => (model.cells.get(`${row}|${col}`) ?? []).map((r) => r.s.session_uuid);

    test('a row worked on a local Monday is under its company and d0', () => {
        expect(at('co-acme', 'd0')).toEqual(['mon']);
        expect(model.cols.map((c) => c.id)).toEqual(['d0', 'd1', 'd2', 'd3', 'd4', 'd5', 'd6']);
        expect(model.rowTally.get('co-acme')?.n).toBe(2);
    });

    test('the activity time stands in for a missing work time, and other companies stay apart', () => {
        expect(at('co-acme', 'd4')).toEqual(['fri']);
        expect(at('co-no-company', 'd6')).toEqual(['sun']);
        expect(model.colTally.get('d0')?.n).toBe(1);
    });
});

describe('pivot find', () => {
    const rows = rowsFromGroups(
        [group({ name: 'acme-app', key: 'a', project: project('Acme'), sessions: [
            session({ session_uuid: 'hit', title: 'alpha run', label: 'alpha run', state: 'asleep', last_work_at: local(2026, 9, 12, 23) }),
            session({ session_uuid: 'miss', title: 'beta run', label: 'beta run', state: 'asleep', last_work_at: local(2026, 9, 12, 23) }),
        ] })],
        [],
        'no project',
    );

    test('a row that misses the find text stays in the matrix and is marked as a miss', () => {
        const model = buildPivot(rows, 'company', 'weekday', { ...ctx, find: 'alpha' });
        expect((model.cells.get('co-acme|d0') ?? []).map((r) => r.s.session_uuid).sort()).toEqual(['hit', 'miss']);
        expect([...model.misses]).toEqual(['miss']);
        expect(model.rowTally.get('co-acme')?.n).toBe(2);
    });
});
