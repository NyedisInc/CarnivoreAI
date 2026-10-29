import { describe, expect, test } from 'vitest';

import type { ProjectPresenceRow, ProjectRow } from '../sessions/types';
import type { TreeSessionRow } from './project-groups';
import {
    PROJECT_WORK_UNRECORDED_KEY,
    presenceFor,
    projectNodeView,
    resolveProjectId,
    workAttrs,
} from './project-node';

function presenceMap(...rows: ProjectPresenceRow[]): Map<string, ProjectPresenceRow> {
    const map = new Map<string, ProjectPresenceRow>();
    for (const row of rows) {
        if (row.raw_path) map.set(row.raw_path as string, row);
        if (row.root) map.set(row.root as string, row);
    }
    return map;
}

function view(
    project: ProjectRow,
    presence = new Map<string, ProjectPresenceRow>(),
    byProjectId = new Map<number, TreeSessionRow[]>(),
) {
    return projectNodeView(project, 0, { presence, byProjectId });
}

describe('presence: four outcomes, and only two of them refuse', () => {
    test('a PRESENT project is not disabled and draws no badge state', () => {
        const v = view(
            { name: 'api', path: '/p', root: '/p' },
            presenceMap({ raw_path: '/p', root: '/p', presence: 'present' }),
        );
        expect(v.presenceState).toBe('present');
        expect(v.isDisabled).toBe(false);
    });

    test('an UNPROBED project reads `unchecked` and every action is allowed', () => {
        const v = view({ name: 'api', path: '/p', root: '/p' });
        expect(v.presenceState).toBe('unchecked');
        expect(v.isDisabled).toBe(false);
    });

    test('MISSING disables the row', () => {
        const v = view(
            { name: 'api', path: '/p', root: '/p' },
            presenceMap({ raw_path: '/p', root: '/p', presence: 'missing' }),
        );
        expect(v.presenceState).toBe('missing');
        expect(v.isDisabled).toBe(true);
    });

    test('UNREACHABLE disables the row AND keeps the server\'s reason', () => {
        const v = view(
            { name: 'api', path: '/p', root: '/p' },
            presenceMap({
                raw_path: '/p', root: '/p',
                presence: 'unreachable', presence_detail: 'EACCES',
            }),
        );
        expect(v.presenceState).toBe('unreachable');
        expect(v.isDisabled).toBe(true);
        expect(v.presenceDetail).toBe('EACCES');
    });

    test('MISSING and UNREACHABLE are two states, never one', () => {
        const missing = view({ name: 'a', path: '/p', root: '/p' },
            presenceMap({ root: '/p', presence: 'missing' }));
        const unreachable = view({ name: 'a', path: '/p', root: '/p' },
            presenceMap({ root: '/p', presence: 'unreachable' }));
        expect(missing.presenceState).not.toBe(unreachable.presenceState);
    });

    test('an unrecognised presence value degrades to `unchecked`, not to disabled', () => {
        const v = view({ name: 'a', path: '/p', root: '/p' },
            presenceMap({ root: '/p', presence: 'something_new' }));
        expect(v.presenceState).toBe('unchecked');
        expect(v.isDisabled).toBe(false);
    });
});

describe('presence lookup: ROOT first, then the raw config path', () => {
    test('the root spelling wins when both are indexed', () => {
        const row = presenceFor(
            { name: 'a', path: '/short', root: '/long' },
            presenceMap(
                { raw_path: '/short', presence: 'missing' },
                { root: '/long', presence: 'present' },
            ),
        );
        expect(row?.presence).toBe('present');
    });

    test('a presence row keyed ONLY by raw_path still resolves', () => {
        const row = presenceFor(
            { name: 'a', path: '/short', root: '/long' },
            presenceMap({ raw_path: '/short', presence: 'missing' }),
        );
        expect(row?.presence).toBe('missing');
    });

    test('no match at all answers null rather than throwing', () => {
        expect(presenceFor({ name: 'a' }, new Map())).toBeNull();
    });
});

describe('the project id ladder, and why row 0 is not null', () => {
    test('the project\'s OWN id wins over a stale presence-map id', () => {
        expect(resolveProjectId({ name: 'a', id: 7 }, { id: 9 })).toBe(7);
    });

    test('the presence map is the fallback for a project not yet imported', () => {
        expect(resolveProjectId({ name: 'a', id: null }, { id: 9 })).toBe(9);
    });

    test('a null id everywhere answers null, and NEVER row 0', () => {
        expect(resolveProjectId({ name: 'a', id: null }, null)).toBeNull();
    });

    test('a REAL row 0 is kept, because 0 is an id and not an absence', () => {
        expect(resolveProjectId({ name: 'a', id: 0 }, null)).toBe(0);
    });

    test('a null-id project draws NO children even when sessions claim id 0', () => {
        const v = view(
            { name: 'a', id: null },
            new Map(),
            new Map([[0, [{ name: 'cloude_x' }]]]),
        );
        expect(v.children).toEqual([]);
        expect(v.hasChildren).toBe(false);
    });

    test('three projects on one root each resolve their OWN id, not a shared one', () => {
        const byProjectId = new Map<number, TreeSessionRow[]>([
            [1, [{ name: 'cloude_one' }]],
            [2, [{ name: 'cloude_two' }]],
        ]);
        const presence = presenceMap({ raw_path: '/shared', root: '/shared', id: 1 });
        const a = view({ name: 'a', id: 1, path: '/shared', root: '/shared' }, presence, byProjectId);
        const b = view({ name: 'b', id: 2, path: '/shared', root: '/shared' }, presence, byProjectId);
        expect(a.children.map((s) => s.name)).toEqual(['cloude_one']);
        expect(b.children.map((s) => s.name)).toEqual(['cloude_two']);
    });
});

describe('archived is orthogonal to presence', () => {
    test('an archived project is NOT disabled', () => {
        const v = view({ name: 'a', archived_at: '2026-01-01' });
        expect(v.isArchived).toBe(true);
        expect(v.isDisabled).toBe(false);
    });

    test('a project can be archived AND missing at once', () => {
        const v = view(
            { name: 'a', path: '/p', root: '/p', archived_at: 'yes' },
            presenceMap({ root: '/p', presence: 'missing' }),
        );
        expect(v.isArchived).toBe(true);
        expect(v.isDisabled).toBe(true);
    });

    test('a live project carries no archived flag', () => {
        expect(view({ name: 'a' }).isArchived).toBe(false);
    });
});

describe('foldability, and what the count chip is allowed to claim', () => {
    test('children alone make a node foldable and give it a count', () => {
        const v = view({ name: 'a', id: 1 }, new Map(),
            new Map([[1, [{ name: 'x' }]]]));
        expect(v.foldable).toBe(true);
        expect(v.hasChildren).toBe(true);
    });

    test('a description alone makes a node foldable with NO count', () => {
        const v = view({ name: 'a', id: 1, description: 'notes' });
        expect(v.foldable).toBe(true);
        expect(v.hasChildren).toBe(false);
        expect(v.hasDescription).toBe(true);
    });

    test('neither means the node does not fold at all', () => {
        const v = view({ name: 'a', id: 1 });
        expect(v.foldable).toBe(false);
    });

    test('a whitespace-only description is NO description', () => {
        expect(view({ name: 'a', description: '   ' }).hasDescription).toBe(false);
    });

    test('the node key is stable and names the project', () => {
        expect(view({ name: 'api' }).nodeKey).toBe('project:api');
    });
});

describe('work recency: unrecorded is visibly distinct, not silently last', () => {
    test('a recorded stamp rides on the row and hovers nothing', () => {
        const w = workAttrs('2026-09-01T00:00:00Z', PROJECT_WORK_UNRECORDED_KEY);
        expect(w).toEqual({
            state: 'recorded', at: '2026-09-01T00:00:00Z', titleKey: null,
        });
    });

    test('a null stamp is UNRECORDED and carries the explanation key', () => {
        const w = workAttrs(null, PROJECT_WORK_UNRECORDED_KEY);
        expect(w.state).toBe('unrecorded');
        expect(w.at).toBeNull();
        expect(w.titleKey).toBe(PROJECT_WORK_UNRECORDED_KEY);
    });

    test('the project view reads `work_at` off the project itself', () => {
        expect(view({ name: 'a', work_at: '2026-09-01' }).work.state).toBe('recorded');
        expect(view({ name: 'a' }).work.state).toBe('unrecorded');
    });
});

describe('the fold key follows the stable id, not the name', () => {
    test('a proven id keys the node, so a rename keeps its fold', () => {
        expect(view({ name: 'api', id: 7 }).nodeKey).toBe('project:7');
        expect(view({ name: 'renamed', id: 7 }).nodeKey).toBe('project:7');
    });
});
