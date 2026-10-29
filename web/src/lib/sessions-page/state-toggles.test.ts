import { describe, expect, it } from 'vitest';
import type { HistoryProject, HistorySession } from '../projects-shared/history-api';
import { NO_FILTERS, filtersActive, passes, toggleState, type Filters, type PageRow, type Signals } from './filters';
import { closedShown } from './closed-model';
import { projectBands } from './inactive-projects';
import type { LensGroup } from './lenses';

const mk = (uuid: string, state: 'running' | 'asleep'): PageRow => ({
    s: { session_uuid: uuid, title: uuid, label: uuid, state, agent_family: 'claude' } as HistorySession,
    groupKey: 'g', projectRef: null, project: 'p', company: null, computer: null, provider: 'claude',
});
const sig = (working: string[], needs: string[]): Signals => ({
    live: (s) => (working.includes(s.session_uuid) ? { activity_status: 'working' } : needs.includes(s.session_uuid) ? { activity_status: 'question' } : { activity_status: 'idle' }) as never,
    asleepUnread: () => false,
});
const labels = { noCompany: 'none', thisComputer: 'here' };
const ids = (rows: PageRow[], f: Filters, s: Signals): string[] => rows.filter((r) => passes(r, f, s, labels)).map((r) => r.s.session_uuid);

describe('state toggles show these kinds', () => {
    const rows = [mk('work', 'running'), mk('ask', 'running'), mk('idle', 'running'), mk('zzz', 'asleep')];
    const s = sig(['work'], ['ask']);

    it('starts with working and sleep on, and a live question row shows under working', () => {
        expect(NO_FILTERS.on).toEqual(['working', 'sleep']);
        expect(ids(rows, { ...NO_FILTERS }, s)).toEqual(['work', 'ask', 'idle', 'zzz']);
    });

    it('is a union: sleep alone hides every live row, questions alone shows only what needs the owner', () => {
        expect(ids(rows, { ...NO_FILTERS, on: ['sleep'] }, s)).toEqual(['zzz']);
        expect(ids(rows, { ...NO_FILTERS, on: ['questions'] }, s)).toEqual(['ask']);
        expect(ids(rows, { ...NO_FILTERS, on: ['questions', 'sleep'] }, s)).toEqual(['ask', 'zzz']);
        expect(ids(rows, { ...NO_FILTERS, on: ['working', 'questions'] }, s)).toEqual(['work', 'ask', 'idle']);
    });

    it('closed rows follow the closed toggle, off by default', () => {
        const closed = { ...mk('gone', 'running'), s: { ...mk('gone', 'running').s, state: 'closed' } } as PageRow;
        expect(closedShown(closed, { ...NO_FILTERS }, labels)).toBe(false);
        expect(closedShown(closed, { ...NO_FILTERS, on: [...NO_FILTERS.on, 'closed'] }, labels)).toBe(true);
    });

    it('removed (archived) rows follow the archive toggle, or closed only once show-hidden is on', () => {
        const removed = { ...mk('arch', 'running'), s: { ...mk('arch', 'running').s, state: 'removed' } } as PageRow;
        expect(closedShown(removed, { ...NO_FILTERS, on: ['archived'] }, labels)).toBe(true);
        expect(closedShown(removed, { ...NO_FILTERS, on: [...NO_FILTERS.on, 'closed'] }, labels)).toBe(false);
        expect(closedShown(removed, { ...NO_FILTERS, on: [...NO_FILTERS.on, 'closed'] }, labels, true)).toBe(true);
    });

    it('flips a toggle both ways in bar order without mutating; only a change from the defaults is active', () => {
        const once = toggleState(NO_FILTERS.on, 'closed');
        expect(once).toEqual(['working', 'sleep', 'closed']);
        expect(toggleState(once, 'closed')).toEqual(['working', 'sleep']);
        expect(toggleState(['working'], 'sleep')).toEqual(['working', 'sleep']);
        expect(filtersActive({ ...NO_FILTERS, on: once })).toBe(true);
        expect(filtersActive({ ...NO_FILTERS })).toBe(false);
    });
});

describe('inactive group in the left panel', () => {
    const proj = (id: number, name: string): HistoryProject => ({ id, name, root: null, description: null, archived_at: null, last_opened_at: null, created_at: null, default_theme: null });
    const grp = (id: number, label: string, live: number): LensGroup => ({ key: `project:${id}`, label, bits: [], measure: '', rows: [], count: live, live, project: proj(id, label), provider: null });

    it('puts every project without a live session in the inactive set, a to z, after the active ones', () => {
        const b = projectBands([grp(1, 'live', 1), grp(2, 'beta', 0), grp(3, 'alpha', 0)], [], '', true);
        expect(b.groups.map((g) => g.label)).toEqual(['live', 'alpha', 'beta']);
        expect([...b.inactive]).toEqual(['project:3', 'project:2']);
    });
});
