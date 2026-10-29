import type { Component } from 'svelte';
import { mountPanel, unmountPanel } from '../mount';
import CascadeMenu from '../drawer-tabs/CascadeMenu.svelte';
import type { MenuNode } from '../drawer-tabs/add-component-menu';
import { layoutsBridge } from '../layouts-bridge/bridge';
import type { Layout } from '../layouts-bridge/api.svelte';
import { t } from '../i18n/index.svelte';
import { companyList } from '../companies';
import { fileProject, newCompanyPrompt } from '../sidebar-shell/company-actions';
import { commitAssignment } from '../sidebar-shell/group-assign';
import { announceFailure, reasonOf } from '../sidebar-shell/interaction-globals';

const CONTAINER_ID = 'add-to-cascade-menu';

export const ADD_TO_CASCADE_CONTAINER_ID = CONTAINER_ID;

interface LegacyRow {
  name: string;
  label?: string | null;
  session_uuid?: string | null;
  kind?: string | null;
}

interface GroupRecord {
  group_uuid: string;
  name: string;
  member_session_uuids?: string[];
}

interface GroupStoreGlobal {
  isUsable(): boolean;
  current(): { groups: GroupRecord[] };
  groupOf(name: string): string | null;
  groupByUuid(uuid: string): GroupRecord | null;
}

interface KindGroupsGlobal {
  isAgentKind(row: LegacyRow): boolean;
}

interface SessionSidebarGlobal {
  _rows?: LegacyRow[];
}

interface LegacyGlobals {
  SessionSidebarGroupStore?: GroupStoreGlobal;
  SessionSidebarKindGroups?: KindGroupsGlobal;
  SessionSidebar?: SessionSidebarGlobal;
}

function legacy(): LegacyGlobals {
  return globalThis as unknown as LegacyGlobals;
}

function agentRows(): LegacyRow[] {
  const rows = legacy().SessionSidebar?._rows ?? [];
  const kinds = legacy().SessionSidebarKindGroups;
  return kinds ? rows.filter((r) => kinds.isAgentKind(r)) : [];
}

function displayName(row: LegacyRow): string {
  return row.label || row.name;
}

function layoutList(): Layout[] {
  return layoutsBridge.list();
}

function isLayoutMember(layout: Layout, sessionUuid: string | null | undefined): boolean {
  return !!sessionUuid && layout.members.some((m) => m.session_uuid === sessionUuid);
}

async function assignGroup(name: string, groupUuid: string | null): Promise<void> {
  try {
    await commitAssignment(name, groupUuid);
  } catch (err) {
    announceFailure(t('sidebar.group.assign_failed', { name, reason: reasonOf(err) }));
  }
}

async function addSessionToLayout(layoutUuid: string, sessionUuid: string): Promise<void> {
  const name = layoutsBridge.get(layoutUuid)?.name ?? '';
  try {
    await layoutsBridge.addMember(layoutUuid, sessionUuid);
  } catch (err) {
    announceFailure(t('layout.add.failed', { name, reason: reasonOf(err) }));
  }
}

async function addGroupToLayout(layoutUuid: string, memberUuids: readonly string[]): Promise<void> {
  const layout = layoutsBridge.get(layoutUuid);
  const already = new Set((layout?.members ?? []).map((m) => m.session_uuid));
  const pending = memberUuids.filter((uuid) => !already.has(uuid));
  let added = 0;
  for (const uuid of pending) {
    try {
      // eslint-disable-next-line no-await-in-loop -- sequential on purpose: each write bumps the Layout's revision the next one reads
      await layoutsBridge.addMember(layoutUuid, uuid);
      added += 1;
    } catch (err) {
      announceFailure(t('layout.add.group_partial', { added, total: pending.length, name: layout?.name ?? '', reason: reasonOf(err) }));
      return;
    }
  }
}

function groupChildrenForAgent(name: string): MenuNode[] {
  const store = legacy().SessionSidebarGroupStore;
  if (!store || !store.isUsable()) {
    return [{ id: 'unavailable', label: t('sidebar.add_to.groups_unavailable'), blocked: t('sidebar.add_to.groups_unavailable') }];
  }
  const current = store.groupOf(name);
  const groups = store.current().groups.filter((g) => g.group_uuid !== current);
  return groups.map((g) => ({
    id: g.group_uuid,
    label: g.name,
    run: () => {
      finish();
      void assignGroup(name, g.group_uuid);
    },
  }));
}

function layoutChildrenForAgent(sessionUuid: string | null): MenuNode[] {
  const list = layoutList().filter((l) => !isLayoutMember(l, sessionUuid));
  return list.map((l) => ({
    id: l.layout_uuid,
    label: l.name,
    run: () => {
      finish();
      if (sessionUuid) void addSessionToLayout(l.layout_uuid, sessionUuid);
    },
  }));
}

function agentChildrenForGroup(groupUuid: string): MenuNode[] {
  const store = legacy().SessionSidebarGroupStore;
  return agentRows()
    .filter((r) => store?.groupOf(r.name) !== groupUuid)
    .map((r) => ({
      id: r.name,
      label: displayName(r),
      run: () => {
        finish();
        void assignGroup(r.name, groupUuid);
      },
    }));
}

function layoutChildrenForGroup(groupUuid: string): MenuNode[] {
  const store = legacy().SessionSidebarGroupStore;
  const memberUuids = (store?.groupByUuid(groupUuid)?.member_session_uuids ?? []).filter(Boolean);
  if (!memberUuids.length) return [];
  return layoutList()
    .filter((l) => memberUuids.some((u) => !isLayoutMember(l, u)))
    .map((l) => ({
      id: l.layout_uuid,
      label: l.name,
      run: () => {
        finish();
        void addGroupToLayout(l.layout_uuid, memberUuids);
      },
    }));
}

function agentChildrenForLayout(layoutUuid: string): MenuNode[] {
  const layout = layoutsBridge.get(layoutUuid);
  return agentRows()
    .filter((r) => !layout || !isLayoutMember(layout, r.session_uuid))
    .filter((r) => !!r.session_uuid)
    .map((r) => ({
      id: r.name,
      label: displayName(r),
      run: () => {
        finish();
        void addSessionToLayout(layoutUuid, r.session_uuid as string);
      },
    }));
}

function groupChildrenForLayout(layoutUuid: string): MenuNode[] {
  const store = legacy().SessionSidebarGroupStore;
  const layout = layoutsBridge.get(layoutUuid);
  if (!store || !store.isUsable() || !layout) return [];
  return store.current().groups
    .filter((g) => {
      const memberUuids = (g.member_session_uuids ?? []).filter(Boolean);
      return memberUuids.length > 0 && memberUuids.some((u) => !isLayoutMember(layout, u));
    })
    .map((g) => ({
      id: g.group_uuid,
      label: g.name,
      run: () => {
        finish();
        void addGroupToLayout(layoutUuid, (g.member_session_uuids ?? []).filter(Boolean));
      },
    }));
}

function branch(id: string, label: string, children: MenuNode[], emptyReason: string): MenuNode {
  return children.length
    ? { id, label, children }
    : { id, label, blocked: emptyReason };
}

const CASCADE = CascadeMenu as unknown as Component<
  { root: MenuNode[]; anchor: HTMLElement | null; label: string; onClose: () => void; nestedIn?: HTMLElement | null },
  Record<string, unknown>
>;

interface OpenOptions {
  parentEl?: HTMLElement | null;
  onFinish?: () => void;
}

let outerFinish: (() => void) | null = null;

function close(): void {
  outerFinish = null;
  unmountPanel(CONTAINER_ID);
}

function finish(): void {
  const done = outerFinish;
  close();
  done?.();
}

function open(root: MenuNode[], anchor: HTMLElement, label: string, opts: OpenOptions = {}): void {
  outerFinish = opts.onFinish ?? null;
  mountPanel(CONTAINER_ID, CASCADE, { root, anchor, label, onClose: close, nestedIn: opts.parentEl ?? null });
}

function sessionBranches(name: string, sessionUuid: string | null): MenuNode[] {
  return [
    branch('group', t('sidebar.add_to.group'), groupChildrenForAgent(name), t('sidebar.add_to.no_other_groups')),
    branch('layout', t('sidebar.add_to.layout'), layoutChildrenForAgent(sessionUuid), t('sidebar.add_to.no_layouts_yet')),
  ];
}

function layoutBranches(layoutUuid: string): MenuNode[] {
  return [
    branch('agents', t('sidebar.add_to.agents'), agentChildrenForLayout(layoutUuid), t('sidebar.add_to.no_agents')),
    branch('groups', t('sidebar.add_to.groups'), groupChildrenForLayout(layoutUuid), t('sidebar.add_to.no_groups')),
  ];
}

function openForSession(anchor: HTMLElement, name: string, sessionUuid: string | null, opts: OpenOptions = {}): void {
  open(
    sessionBranches(name, sessionUuid),
    anchor,
    t('sidebar.add_to.agent_title', { name }),
    opts,
  );
}

function groupBranches(groupUuid: string): MenuNode[] {
  return [
    branch('agents', t('sidebar.add_to.agents'), agentChildrenForGroup(groupUuid), t('sidebar.add_to.no_other_agents')),
    branch('layouts', t('sidebar.add_to.layouts'), layoutChildrenForGroup(groupUuid), t('sidebar.add_to.no_layouts_to_add_to')),
  ];
}

function openForGroup(anchor: HTMLElement, groupUuid: string, opts: OpenOptions = {}): void {
  const name = legacy().SessionSidebarGroupStore?.groupByUuid(groupUuid)?.name ?? t('sidebar.add_to.this_group');
  open(
    groupBranches(groupUuid),
    anchor,
    t('sidebar.add_to.target_title', { name }),
    opts,
  );
}

function openForLayout(anchor: HTMLElement, layoutUuid: string, opts: OpenOptions = {}): void {
  const name = layoutsBridge.get(layoutUuid)?.name ?? t('sidebar.add_to.this_layout');
  open(
    layoutBranches(layoutUuid),
    anchor,
    t('sidebar.add_to.target_title', { name }),
    opts,
  );
}

function projectBranches(projectName: string): MenuNode[] {
  const children: MenuNode[] = companyList().map((c) => ({
    id: `c:${c.id}`,
    label: c.name,
    run: () => {
      finish();
      void fileProject(projectName, c);
    },
  }));
  children.push({
    id: 'new-company',
    label: t('sidebar.company.new.leaf'),
    run: () => {
      finish();
      void newCompanyPrompt(projectName);
    },
  });
  return [{ id: 'company', label: t('sidebar.company.branch'), children }];
}

function openForProject(anchor: HTMLElement, projectName: string, opts: OpenOptions = {}): void {
  open(projectBranches(projectName), anchor, t('sidebar.project.add_to.title', { name: projectName }), opts);
}

export const addToMenuBridge = { openForSession, openForGroup, openForLayout, openForProject, close };

export const addToNodes = { forGroup: groupBranches, forProject: projectBranches, forSession: sessionBranches, forLayout: layoutBranches };
