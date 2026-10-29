import { describe, expect, test } from 'vitest';
import { lensGroups, type LensContext } from './lenses';
import { rowsFromGroups, type Signals } from './filters';
import { nextSort, sortGroups } from './sorting';
import { group, session } from '../projects-shared/test-fixtures';

const NOW = Date.UTC(2026, 9, 14, 12, 0, 0);

const sig: Signals = { live: () => undefined, asleepUnread: () => false };

const ctx: LensContext = {
    t: (key) => key,
    now: NOW,
    sig,
    isPinned: () => false,
    usage: null,
    conversations: {},
    age: (iso) => iso ?? '',
    latest: () => '',
    noCompany: 'no company',
    thisComputer: 'this computer',
};

const row = (uuid: string, name: string, at: string) => session({ session_uuid: uuid, title: name, label: name, state: 'asleep', last_activity_at: at });

const GROUPS = [
    group({ name: 'zeta', key: 'zeta', sessions: [row('z1', 'bravo', '2026-10-14T09:00:00Z'), row('z2', 'Alpha', '2026-10-13T09:00:00Z')] }),
    group({ name: 'Beta', key: 'Beta', sessions: [row('b1', 'delta', '2026-10-12T09:00:00Z'), row('b2', 'charlie', '2026-10-14T10:00:00Z')] }),
    group({ name: 'alpha', key: 'alpha', sessions: [row('a1', 'echo', '2026-10-11T09:00:00Z')] }),
];
const rows = rowsFromGroups(GROUPS, [], 'no project');

describe('sessions list lenses', () => {
    test('the project lens lists its groups a to z, case-insensitive', () => {
        const labels = lensGroups('project', rows, ctx).map((g) => g.label);
        expect(labels).toEqual(['alpha', 'Beta', 'zeta']);
    });

    test('a header sort reorders the rows inside each group and never moves a group', () => {
        const groups = lensGroups('project', rows, ctx);
        const names = (gs: typeof groups) => gs.map((g) => g.rows.map((r) => r.s.title));
        expect(names(groups)).toEqual([['echo'], ['charlie', 'delta'], ['bravo', 'Alpha']]);

        const byName = sortGroups(groups, nextSort(null, 'name'), 'project', ctx);
        expect(byName.map((g) => g.label)).toEqual(['alpha', 'Beta', 'zeta']);
        expect(names(byName)).toEqual([['echo'], ['charlie', 'delta'], ['Alpha', 'bravo']]);
        expect(byName.map((g) => g.rows.length)).toEqual([1, 2, 2]);

        const reversed = sortGroups(groups, nextSort(nextSort(null, 'name'), 'name'), 'project', ctx);
        expect(names(reversed)).toEqual([['echo'], ['delta', 'charlie'], ['bravo', 'Alpha']]);
        expect(reversed.map((g) => g.label)).toEqual(['alpha', 'Beta', 'zeta']);
    });
});
