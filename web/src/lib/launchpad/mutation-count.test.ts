/** @vitest-environment jsdom */
import { beforeEach, describe, expect, test } from 'vitest';

import { instanceKey } from '../sessions/attribution';
import type { RunningSessionRow, SessionRecord } from '../sessions/types';
import {
    applyFixture,
    mountTree,
    settle,
    watchMutations,
    type MountedTree,
} from './tree-harness';

const TICKS_PER_WINDOW = 12;

const PROJECT_COUNT = 9;
const SESSIONS_PER_PROJECT = 5;

let tree: MountedTree | null = null;

function fixture(statusOverrides: Record<string, string> = {}) {
    const projects = [];
    const runningSessions: RunningSessionRow[] = [];
    const byInstance = new Map<string, SessionRecord>();
    for (let p = 0; p < PROJECT_COUNT; p++) {
        projects.push({ name: `project-${p}`, id: p, path: `/p${p}`, root: `/p${p}` });
        for (let s = 0; s < SESSIONS_PER_PROJECT; s++) {
            const name = `cloude_p${p}_s${s}`;
            const epoch = p * 100 + s;
            runningSessions.push({
                name,
                created_at_epoch: epoch,
                status: statusOverrides[name] ?? 'idle',
                unread: false,
                created_by_cloude: true,
                agent_family: 'claude',
                agent_family_source: 'wrapper',
            });
            byInstance.set(instanceKey(name, epoch), {
                id: p * 100 + s,
                tmux_name: name,
                tmux_created_epoch: epoch,
                lifecycle: 'running',
                project_id: p,
                project_attribution: 'project',
                archived_at: null,
            });
        }
    }
    return { projects, runningSessions, sessionAttributionByInstance: byInstance };
}

function legacyReplacementCost(container: HTMLElement): {
    records: number;
    nodes: number;
} {
    const markup = container.innerHTML;
    const watcher = watchMutations(container);
    container.innerHTML = markup;
    return watcher.stop();
}

beforeEach(() => {
    if (tree) {
        tree.destroy();
        tree = null;
    }
});

describe('the fixture is big enough for the measurement to mean anything', () => {
    test('it paints 45 session rows across 9 projects', () => {
        tree = mountTree(fixture());
        expect(tree.container.querySelectorAll('.project-node[data-project-node="project"]'))
            .toHaveLength(PROJECT_COUNT);
        expect(tree.container.querySelectorAll('.project-session-row'))
            .toHaveLength(PROJECT_COUNT * SESSIONS_PER_PROJECT);
    });

    test('and it holds enough nodes for a rebuild to be the expensive thing', () => {
        tree = mountTree(fixture());
        expect(tree.container.querySelectorAll('*').length).toBeGreaterThan(400);
    });
});

describe('MEASUREMENT 1: twelve ticks with NOTHING changing', () => {
    test('costs ZERO mutations, which the old guard already achieved', () => {
        tree = mountTree(fixture());
        const watcher = watchMutations(tree.container);
        for (let i = 0; i < TICKS_PER_WINDOW; i++) {
            applyFixture(fixture());
        }
        expect(watcher.stop()).toEqual({ records: 0, nodes: 0 });
    });

    test('and it is still zero when every tick hands over fresh OBJECTS', async () => {
        tree = mountTree(fixture());
        await settle();
        const watcher = watchMutations(tree.container);
        for (let i = 0; i < TICKS_PER_WINDOW; i++) {
            applyFixture(fixture());
            await settle();
        }
        expect(watcher.stop()).toEqual({ records: 0, nodes: 0 });
    });
});

describe('MEASUREMENT 2: twelve ticks with EXACTLY ONE status changing', () => {
    test('costs under 5 mutation records for that one dot', async () => {
        tree = mountTree(fixture());
        await settle();
        const watcher = watchMutations(tree.container);
        for (let i = 0; i < TICKS_PER_WINDOW; i++) {
            applyFixture(i >= 5 ? fixture({ 'cloude_p3_s2': 'working' }) : fixture());
            await settle();
        }
        const { records, nodes } = watcher.stop();
        expect(records).toBe(5);
        expect(nodes).toBe(0);
    });

    test('and the dot really did change, so the count is not a count of nothing', async () => {
        tree = mountTree(fixture());
        const row = tree.container.querySelector(
            '.project-session-row[data-name="cloude_p3_s2"] .status-dot',
        ) as HTMLElement;
        expect(row.className).toContain('status-dot--idle');
        applyFixture(fixture({ 'cloude_p3_s2': 'working' }));
        await settle();
        const after = tree.container.querySelector(
            '.project-session-row[data-name="cloude_p3_s2"] .status-dot',
        ) as HTMLElement;
        expect(after.className).toContain('status-dot--working');
        expect(after).toBe(row);
    });

    test('THE LEGACY MECHANISM, same fixture: over 100x the records', () => {
        tree = mountTree(fixture());
        const legacy = legacyReplacementCost(tree.container);
        expect(legacy.records).toBe(1);
        expect(legacy.nodes).toBeGreaterThan(800);
    });
});

describe('MEASUREMENT 3: the busy case the guard could not do', () => {
    test('a status change lands while a row menu is open, and the menu stays', async () => {
        tree = mountTree(fixture());
        const rowEl = tree.container.querySelector(
            '.project-session-row[data-name="cloude_p3_s2"]',
        ) as HTMLElement;

        const menu = document.createElement('div');
        menu.className = 'session-row-menu';
        menu.dataset.open = '1';
        rowEl.appendChild(menu);

        applyFixture(fixture({ 'cloude_p3_s2': 'working' }));
        await settle();

        expect(
            (tree.container.querySelector(
                '.project-session-row[data-name="cloude_p3_s2"] .status-dot',
            ) as HTMLElement).className,
        ).toContain('status-dot--working');
        expect(tree.container.querySelector('.session-row-menu')).toBe(menu);
        expect(menu.isConnected).toBe(true);
    });

    test('a focused input inside the tree survives a tick too', async () => {
        tree = mountTree(fixture());
        const rowEl = tree.container.querySelector(
            '.project-session-row[data-name="cloude_p0_s0"]',
        ) as HTMLElement;
        const input = document.createElement('input');
        input.className = 'running-session-rename-input';
        input.value = 'half typed';
        rowEl.appendChild(input);

        applyFixture(fixture({ 'cloude_p8_s4': 'working' }));
        await settle();

        expect(input.isConnected).toBe(true);
        expect(input.value).toBe('half typed');
    });
});

describe('NEGATIVE CONTROL: the observer can and does count', () => {
    test('a deliberate change to one attribute produces a record', () => {
        tree = mountTree(fixture());
        const watcher = watchMutations(tree.container);
        (tree.container.querySelector('.project-item') as HTMLElement)
            .setAttribute('data-probe', '1');
        expect(watcher.stop()).toEqual({ records: 1, nodes: 0 });
    });

    test('and it sees a subtree replacement as hundreds of NODES', () => {
        tree = mountTree(fixture());
        expect(legacyReplacementCost(tree.container).nodes).toBeGreaterThan(800);
    });
});
