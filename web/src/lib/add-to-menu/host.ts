import type { Component } from 'svelte';
import { mountPanel, unmountPanel } from '../mount';
import CascadeMenu from '../drawer-tabs/CascadeMenu.svelte';
import type { MenuNode } from '../drawer-tabs/add-component-menu';
import { layoutsBridge } from '../layouts-bridge/bridge';
import type { Layout } from '../layouts-bridge/api.svelte';
import { t } from '../i18n/index.svelte';
import { companyList } from '../companies';
import { fileProject, newCompanyPrompt } from '../sidebar-shell/company-actions';

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

interface GroupActionsGlobal {
  commitAssignment(name: string, groupUuid: string | null): Promise<boolean>;
}

interface KindGroupsGlobal {
  isAgentKind(row: LegacyRow): boolean;
}

interface SessionSidebarGlobal {
  _rows?: LegacyRow[];
}

interface LegacyGlobals {
  SessionSidebarGroupStore?: GroupStoreGlobal;
  SessionSidebarGroupActions?: GroupActionsGlobal;
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

function assignGroup(name: string, groupUuid: string | null): void {
  void legacy().SessionSidebarGroupActions?.commitAssignment(name, groupUuid);
}

function addSessionToLayout(layoutUuid: string, sessionUuid: string): void {
  void layoutsBridge.addMember(layoutUuid, sessionUuid);
}

async function addGroupToLayout(layoutUuid: string, memberUuids: readonly string[]): Promise<void> {
  const layout = layoutsBridge.get(layoutUuid);
  const already = new Set((layout?.members ?? []).map((m) => m.session_uuid));
  for (const uuid of memberUuids) {
    if (already.has(uuid)) continue;
    // eslint-disable-next-line no-await-in-loop -- sequential on purpose: each write bumps the Layout's revision the next one reads
    await layoutsBridge.addMember(layoutUuid, uuid);
  }
}

function groupChildrenForAgent(name: string): MenuNode[] {
  const store = legacy().SessionSidebarGroupStore;
  if (!store || !store.isUsable()) {
    return [{ id: 'unavailable', label: 'groups unavailable', blocked: 'groups unavailable' }];
  }
  const current = store.groupOf(name);
  const groups = store.current().groups.filter((g) => g.group_uuid !== current);
  return groups.map((g) => ({
    id: g.group_uuid,
    label: g.name,
    run: () => {
      finish();
      assignGroup(name, g.group_uuid);
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
      if (sessionUuid) addSessionToLayout(l.layout_uuid, sessionUuid);
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
        assignGroup(r.name, groupUuid);
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
        addSessionToLayout(layoutUuid, r.session_uuid as string);
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
    branch('group', 'Group', groupChildrenForAgent(name), 'no other groups yet'),
    branch('layout', 'Layout', layoutChildrenForAgent(sessionUuid), 'no Layouts yet'),
  ];
}

function layoutBranches(layoutUuid: string): MenuNode[] {
  return [
    branch('agents', 'Agents', agentChildrenForLayout(layoutUuid), 'no agents to add'),
    branch('groups', 'Groups', groupChildrenForLayout(layoutUuid), 'no groups to add'),
  ];
}

function openForSession(anchor: HTMLElement, name: string, sessionUuid: string | null, opts: OpenOptions = {}): void {
  open(
    sessionBranches(name, sessionUuid),
    anchor,
    `Add ${name} to`,
    opts,
  );
}

function groupBranches(groupUuid: string): MenuNode[] {
  return [
    branch('agents', 'Agents', agentChildrenForGroup(groupUuid), 'no other agents to add'),
    branch('layouts', 'Layouts', layoutChildrenForGroup(groupUuid), 'no Layouts to add to'),
  ];
}

function openForGroup(anchor: HTMLElement, groupUuid: string, opts: OpenOptions = {}): void {
  const name = legacy().SessionSidebarGroupStore?.groupByUuid(groupUuid)?.name ?? 'this group';
  open(
    groupBranches(groupUuid),
    anchor,
    `Add to ${name}`,
    opts,
  );
}

function openForLayout(anchor: HTMLElement, layoutUuid: string, opts: OpenOptions = {}): void {
  const name = layoutsBridge.get(layoutUuid)?.name ?? 'this Layout';
  open(
    layoutBranches(layoutUuid),
    anchor,
    `Add to ${name}`,
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
