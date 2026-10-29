import { beforeEach, expect, test, vi } from 'vitest';

const hoisted = vi.hoisted(() => ({
  addMember: vi.fn(),
  get: vi.fn(),
  list: vi.fn(),
  announce: vi.fn(),
  commit: vi.fn(),
}));
vi.mock('../mount', () => ({ mountPanel: vi.fn(), unmountPanel: vi.fn() }));
vi.mock('../drawer-tabs/CascadeMenu.svelte', () => ({ default: {} }));
vi.mock('../layouts-bridge/bridge', () => ({ layoutsBridge: { addMember: hoisted.addMember, get: hoisted.get, list: hoisted.list } }));
vi.mock('../companies', () => ({ companyList: () => [] }));
vi.mock('../sidebar-shell/company-actions', () => ({ fileProject: vi.fn(), newCompanyPrompt: vi.fn() }));
vi.mock('../sidebar-shell/group-assign', () => ({ commitAssignment: (...a: unknown[]) => hoisted.commit(...a) }));
vi.mock('../sidebar-shell/interaction-globals', () => ({ announceFailure: hoisted.announce, reasonOf: (e: unknown) => (e as Error).message }));

import { addToNodes } from './host';
import type { MenuNode } from '../drawer-tabs/add-component-menu';

const layout = { layout_uuid: 'L1', name: 'wall', members: [] as { session_uuid: string }[] };
const settle = async (): Promise<void> => {
  for (let i = 0; i < 6; i++) await Promise.resolve();
};
const leaf = (nodes: MenuNode[], id: string): MenuNode => (nodes.find((n) => n.id === id)!.children as MenuNode[])[0]!;

beforeEach(() => {
  Object.values(hoisted).forEach((fn) => fn.mockReset());
  hoisted.list.mockReturnValue([layout]);
  hoisted.get.mockReturnValue(layout);
  (globalThis as Record<string, unknown>).SessionSidebarGroupStore = {
    isUsable: () => true,
    current: () => ({ groups: [{ group_uuid: 'G1', name: 'g', member_session_uuids: ['u1', 'u2', 'u3'] }] }),
    groupOf: () => null,
    groupByUuid: () => ({ group_uuid: 'G1', name: 'g', member_session_uuids: ['u1', 'u2', 'u3'] }),
  };
});

test('a refused single add to a Layout is announced', async () => {
  hoisted.addMember.mockRejectedValue(new Error('layout_stale'));
  leaf(addToNodes.forSession('a', 'u9'), 'layout').run!();
  await settle();
  expect(hoisted.announce).toHaveBeenCalledWith(expect.stringContaining('layout_stale'));
});

test('a group add that fails on the second member says two of three did not all land', async () => {
  hoisted.addMember.mockResolvedValueOnce({}).mockRejectedValueOnce(new Error('member_unresolved'));
  leaf(addToNodes.forGroup('G1'), 'layouts').run!();
  await settle();
  expect(hoisted.addMember).toHaveBeenCalledTimes(2);
  expect(hoisted.announce).toHaveBeenCalledWith(expect.stringMatching(/added 1 of 3.*member_unresolved/));
});

test('a throwing group move is announced', async () => {
  hoisted.commit.mockRejectedValue(new Error('boom'));
  leaf(addToNodes.forSession('a', 'u9'), 'group').run!();
  await settle();
  expect(hoisted.announce).toHaveBeenCalledWith(expect.stringContaining('boom'));
});
