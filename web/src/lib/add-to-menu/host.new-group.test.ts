import { beforeEach, expect, test, vi } from 'vitest';

const hoisted = vi.hoisted(() => ({ create: vi.fn(), commit: vi.fn() }));
vi.mock('../mount', () => ({ mountPanel: vi.fn(), unmountPanel: vi.fn() }));
vi.mock('../drawer-tabs/CascadeMenu.svelte', () => ({ default: {} }));
vi.mock('../layouts-bridge/bridge', () => ({ layoutsBridge: { addMember: vi.fn(), get: vi.fn(), list: () => [] } }));
vi.mock('../companies', () => ({ companyList: () => [] }));
vi.mock('../sidebar-shell/company-actions', () => ({ fileProject: vi.fn(), newCompanyPrompt: vi.fn() }));
vi.mock('../sidebar-shell/group-assign', () => ({
  commitAssignment: (...a: unknown[]) => hoisted.commit(...a),
  createGroupThenAssign: (...a: unknown[]) => hoisted.create(...a),
}));
vi.mock('../sidebar-shell/interaction-globals', () => ({ announceFailure: vi.fn(), reasonOf: (e: unknown) => (e as Error).message }));

import { addToNodes } from './host';
import type { MenuNode } from '../drawer-tabs/add-component-menu';

const groupLeaves = (): MenuNode[] => (addToNodes.forSession('a', 'u1').find((n) => n.id === 'group')!.children as MenuNode[]);

function holdGroups(groups: Array<[string, string]>, current: string | null): void {
  (globalThis as Record<string, unknown>).SessionSidebarGroupStore = {
    isUsable: () => true,
    current: () => ({ groups: groups.map(([group_uuid, name]) => ({ group_uuid, name })) }),
    groupOf: () => current,
    groupByUuid: () => null,
  };
}

beforeEach(() => {
  hoisted.create.mockReset();
  hoisted.commit.mockReset();
});

test('the last leaf is "new group..." and runs the create-then-file flow for this agent', () => {
  holdGroups([['g1', 'research'], ['g2', 'ops']], 'g1');
  const leaves = groupLeaves();
  expect(leaves.map((n) => n.label)).toEqual(['ops', 'new group...']);
  leaves[1]!.run!();
  expect(hoisted.create).toHaveBeenCalledWith('a');
  expect(hoisted.commit).not.toHaveBeenCalled();
});

test('it is offered even when the agent has no other group to move to', () => {
  holdGroups([['g1', 'research']], 'g1');
  expect(groupLeaves().map((n) => n.label)).toEqual(['new group...']);
});
