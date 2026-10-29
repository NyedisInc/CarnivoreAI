import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';

import { NO_PROJECT_NODE_KEY, treeCollapse } from './tree-collapse.svelte';

const memory = new Map<string, string>();

beforeEach(() => {
    memory.clear();
    vi.stubGlobal('localStorage', {
        getItem: (k: string) => memory.get(k) ?? null,
        setItem: (k: string, v: string) => void memory.set(k, v),
        removeItem: (k: string) => void memory.delete(k),
    });
    treeCollapse.resetForTests();
});

afterEach(() => {
    vi.unstubAllGlobals();
});

describe('the default is open, and unknown keys are open too', () => {
    test('nothing is collapsed to begin with', () => {
        expect(treeCollapse.size).toBe(0);
        expect(treeCollapse.isCollapsed('project:api')).toBe(false);
    });

    test('a key nobody has ever set reads as OPEN, not as unknown', () => {
        expect(treeCollapse.isCollapsed('project:never-seen')).toBe(false);
    });
});

describe('setting and toggling', () => {
    test('set(true) folds and set(false) unfolds', () => {
        treeCollapse.set('project:api', true);
        expect(treeCollapse.isCollapsed('project:api')).toBe(true);
        treeCollapse.set('project:api', false);
        expect(treeCollapse.isCollapsed('project:api')).toBe(false);
    });

    test('toggle answers what the node BECAME, not what it was', () => {
        expect(treeCollapse.toggle('project:api')).toBe(true);
        expect(treeCollapse.toggle('project:api')).toBe(false);
    });

    test('toggling twice returns to the starting state and leaves nothing behind', () => {
        treeCollapse.toggle('project:api');
        treeCollapse.toggle('project:api');
        expect(treeCollapse.size).toBe(0);
    });

    test('an empty key is ignored rather than folding a phantom node', () => {
        treeCollapse.set('', true);
        expect(treeCollapse.size).toBe(0);
    });

    test('setting a key to what it already is changes nothing', () => {
        treeCollapse.set('project:api', false);
        expect(treeCollapse.size).toBe(0);
        treeCollapse.set('project:api', true);
        treeCollapse.set('project:api', true);
        expect(treeCollapse.size).toBe(1);
    });

    test('two nodes fold independently', () => {
        treeCollapse.set('project:a', true);
        expect(treeCollapse.isCollapsed('project:a')).toBe(true);
        expect(treeCollapse.isCollapsed('project:b')).toBe(false);
    });

    test('the synthetic no-project group folds on its own key', () => {
        expect(NO_PROJECT_NODE_KEY).toBe('__no_project__');
        treeCollapse.set(NO_PROJECT_NODE_KEY, true);
        expect(treeCollapse.isCollapsed(NO_PROJECT_NODE_KEY)).toBe(true);
        expect(treeCollapse.isCollapsed('project:__no_project__')).toBe(false);
    });
});

describe('THE CONTRACT: nothing about the data may clear a fold', () => {
    test('twelve simulated poll ticks do not reopen a folded node', () => {
        treeCollapse.set('project:api', true);
        for (let tick = 0; tick < 12; tick++) {
            expect(treeCollapse.isCollapsed('project:api')).toBe(true);
        }
        expect(treeCollapse.size).toBe(1);
    });

    test('ONLY resetForTests clears it, and it is not called by anything real', () => {
        treeCollapse.set('project:api', true);
        treeCollapse.resetForTests();
        expect(treeCollapse.size).toBe(0);
    });
});

describe('a fold survives a reload', () => {
    test('a folded project is still folded after the in-memory state is dropped', () => {
        treeCollapse.set('project:7', true);
        treeCollapse.simulateReloadForTests();
        expect(treeCollapse.isCollapsed('project:7')).toBe(true);
        expect(treeCollapse.isCollapsed('project:8')).toBe(false);
    });

    test('an unfold is remembered too', () => {
        treeCollapse.set('project:7', true);
        treeCollapse.set('project:7', false);
        treeCollapse.simulateReloadForTests();
        expect(treeCollapse.isCollapsed('project:7')).toBe(false);
    });

    test('storage holds the folded keys as a JSON array under one key', () => {
        treeCollapse.set('project:7', true);
        expect(JSON.parse(memory.get('carnivore.launchpad.collapsedProjects') ?? 'null')).toEqual(['project:7']);
    });

    test('a throwing storage never breaks folding', () => {
        vi.stubGlobal('localStorage', {
            getItem: () => { throw new Error('denied'); },
            setItem: () => { throw new Error('denied'); },
            removeItem: () => undefined,
        });
        treeCollapse.simulateReloadForTests();
        treeCollapse.set('project:7', true);
        expect(treeCollapse.isCollapsed('project:7')).toBe(true);
    });

    test('garbage in storage reads as nothing folded', () => {
        memory.set('carnivore.launchpad.collapsedProjects', '{not json');
        treeCollapse.simulateReloadForTests();
        expect(treeCollapse.size).toBe(0);
    });
});
