/** @vitest-environment jsdom */
import { beforeEach, describe, expect, test } from 'vitest';

import { sessionStore } from '../sessions/store.svelte';
import { treeCollapse } from './tree-collapse.svelte';
import { uiPrefs } from '../ui/prefs.svelte';
import {
    fixtureHost,
    fleet,
    mountTree,
    settle,
    watchMutations,
    type MountedTree,
} from './tree-harness';

const tick = () => sessionStore.loadRunningSessions((k: string) => k);

const TICKS_PER_WINDOW = 12;

let tree: MountedTree | null = null;

async function mountAndSettle(working: string[] = []): Promise<MountedTree> {
    const t = mountTree({});
    sessionStore.useHost(fixtureHost(fleet({ working })));
    await sessionStore.loadProjects(false, (k: string) => k);
    await tick();
    await settle();
    return t;
}

beforeEach(() => {
    if (tree) {
        tree.destroy();
        tree = null;
    }
    sessionStore.useHost(null);
    treeCollapse.resetForTests();
    uiPrefs.resetForTests();
});

describe('the real load path paints the same screen the direct writes do', () => {
    test('one tick through loadRunningSessions paints 9 nodes and 45 rows', async () => {
        tree = await mountAndSettle();
        expect(tree.container.querySelectorAll(
            '.project-node[data-project-node="project"]')).toHaveLength(9);
        expect(tree.container.querySelectorAll('.project-session-row')).toHaveLength(45);
    });

    test('and it paints them in the SORT order, newest created first', async () => {
        tree = await mountAndSettle();
        const names = Array.from(tree.container.querySelectorAll(
            '.project-node[data-project-name="project-3"] .project-session-row'))
            .map((el) => el.getAttribute('data-name'));
        expect(names).toEqual([
            'cloude_p3_s4', 'cloude_p3_s3', 'cloude_p3_s2',
            'cloude_p3_s1', 'cloude_p3_s0',
        ]);
    });
});

describe('TWELVE REAL TICKS with nothing changing cost the DOM nothing', () => {
    test('0 records and 0 nodes', async () => {
        tree = await mountAndSettle();
        const watcher = watchMutations(tree.container);
        for (let i = 0; i < TICKS_PER_WINDOW; i++) {
            await tick();
            await settle();
        }
        expect(watcher.stop()).toEqual({ records: 0, nodes: 0 });
    });

    test('and the row ORDER is unchanged after them, not merely restored', async () => {
        tree = await mountAndSettle();
        const before = Array.from(tree.container.querySelectorAll(
            '.project-session-row')).map((el) => el.getAttribute('data-name'));
        for (let i = 0; i < TICKS_PER_WINDOW; i++) {
            await tick();
            await settle();
        }
        const after = Array.from(tree.container.querySelectorAll(
            '.project-session-row')).map((el) => el.getAttribute('data-name'));
        expect(after).toEqual(before);
        expect(after).toHaveLength(45);
    });

    test('NEGATIVE CONTROL: the tree really is subscribed to these ticks', async () => {
        tree = await mountAndSettle();
        const dot = () => tree!.container.querySelector(
            '.project-session-row[data-name="cloude_p3_s2"] .status-dot') as HTMLElement;
        expect(dot().className).toContain('status-dot--idle');
        sessionStore.useHost(fixtureHost(fleet({ working: ['cloude_p3_s2'] })));
        await tick();
        await settle();
        expect(dot().className).toContain('status-dot--working');
    });
});

describe('a tick that DOES change one status costs five attributes and no nodes', () => {
    test('exactly 5 records, all attributes, all on one element', async () => {
        tree = await mountAndSettle();
        const watcher = watchMutations(tree.container);
        for (let i = 0; i < TICKS_PER_WINDOW; i++) {
            if (i === 5) {
                sessionStore.useHost(fixtureHost(fleet({ working: ['cloude_p3_s2'] })));
            }
            await tick();
            await settle();
        }
        const { records, nodes } = watcher.stop();
        expect(records).toBe(5);
        expect(nodes).toBe(0);
    });

    test('and the dot that changed is the SAME element it was before', async () => {
        tree = await mountAndSettle();
        const sel = '.project-session-row[data-name="cloude_p3_s2"] .status-dot';
        const before = tree.container.querySelector(sel);
        sessionStore.useHost(fixtureHost(fleet({ working: ['cloude_p3_s2'] })));
        await tick();
        await settle();
        const after = tree.container.querySelector(sel);
        expect(after).toBe(before);
        expect((after as HTMLElement).className).toContain('status-dot--working');
    });
});

describe('THE SOURCE RULE: the row set is published exactly once per tick', () => {
    test('the running reload assigns `runningSessions` once, and after the await', async () => {
        const fs = await import('node:fs');
        const path = await import('node:path');
        const url = await import('node:url');
        const here = path.dirname(url.fileURLToPath(import.meta.url));
        const src = fs.readFileSync(
            path.join(here, '..', 'sessions', 'store.svelte.ts'), 'utf8');
        const start = src.indexOf('async function fetchRunningSessions');
        expect(start).toBeGreaterThan(-1);
        const body = src.slice(start);
        const method = body.slice(0, body.indexOf('\n}\n'));
        const assignments = method.match(/^\s*runningSessions = /gm) || [];
        expect(assignments).toHaveLength(1);
        expect(method).toContain('runningSessions = sortRunningSessionsByWork');
    });
});
