import { describe, expect, it } from 'vitest';
import type { HistoryProject } from '../projects-shared/history-api';
import type { LensGroup } from './lenses';
import { projectBands } from './inactive-projects';

const proj = (id: number, name: string, archived = false): HistoryProject => ({ id, name, root: null, description: null, archived_at: archived ? '2026-01-01' : null, last_opened_at: null, created_at: null, default_theme: null });
const grp = (id: number, label: string, live: number): LensGroup => ({ key: `project:${id}`, label, bits: [], measure: '', rows: [], count: live, live, project: proj(id, label), provider: null });
const names = (b: { groups: readonly LensGroup[] }): string[] => b.groups.map((g) => g.label);

describe('projectBands', () => {
    const groups = [grp(1, 'zeta', 2), grp(2, 'alpha', 1), grp(3, 'Mango', 0), grp(4, 'bravo', 0)];
    const empties = [proj(5, 'charlie'), proj(6, 'delta', true), proj(3, 'Mango'), proj(7, 'Apple')];

    it('keeps active in lens order, then inactive a to z, archived excluded, no duplicate', () => {
        const b = projectBands(groups, empties, '', true);
        expect(names(b)).toEqual(['zeta', 'alpha', 'Apple', 'bravo', 'charlie', 'Mango']);
        expect([...b.inactive].length).toBe(4);
    });

    it('filters empty projects by name across both bands, case-insensitive', () => {
        expect(names(projectBands(groups, empties, 'CHAR', true))).toEqual(['zeta', 'alpha', 'bravo', 'charlie', 'Mango']);
        expect(names(projectBands(groups, empties, 'app', true)).slice(-1)).toEqual(['Mango']);
        expect(names(projectBands(groups, empties, 'app', true))).toContain('Apple');
    });

    it('leaves the empty projects out while another filter is set', () => {
        expect(names(projectBands(groups, empties, '', false))).toEqual(['zeta', 'alpha', 'bravo', 'Mango']);
    });
});
