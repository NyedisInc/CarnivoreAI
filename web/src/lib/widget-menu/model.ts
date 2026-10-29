import type { MenuNode } from '../drawer-tabs/add-component-menu';
import { t } from '../i18n/index.svelte';
import type { BarSize } from '../widget-bars/bar-settings.svelte';

export const CORE_ID = {
  popOut: 'pop-out',
  focusMain: 'focus-main-window',
  showHeader: 'show-header',
  settings: 'settings',
  extendRow: 'extend-row',
  pullBackRow: 'pull-back-row',
  moveUp: 'widget-move-up',
  moveDown: 'widget-move-down',
  moveToDrawer: 'move-to-drawer',
  moveToBar: 'move-to-bar',
  editLayout: 'edit-layout',
  doneEditing: 'done-editing',
  closeWidget: 'close-widget',
  removeWidget: 'remove-widget',
  closeTab: 'close-tab',
  moveTab: 'move-tab',
  splitRight: 'split-right',
  splitDown: 'split-down',
} as const;

export type ArrangeId = 'extendRow' | 'pullBackRow' | 'moveUp' | 'moveDown' | 'moveToDrawer' | 'moveToBar';

export interface ArrangeEntry {
  item: ArrangeId;
  label?: string;
  blocked?: string;
  run: () => void;
}

export interface WidgetMenuCtx {
  editing: boolean;
  onClose: () => void;
  content?: readonly (readonly MenuNode[])[];
  views?: readonly MenuNode[];
  scopeViews?: readonly MenuNode[];
  settings?: readonly (readonly MenuNode[])[];
  popOut?: (() => void) | null;
  focusMain?: (() => void) | null;
  header?: { shown: boolean; toggle: () => void } | null;
  arrange?: readonly ArrangeEntry[];
  editLayout?: (() => void) | null;
  close?: { run: () => void; instance?: boolean } | null;
  tab?: TabItems | null;
}

export interface TabItems {
  moveTo?: (() => void) | null;
  splitRight?: (() => void) | null;
  splitDown?: (() => void) | null;
  close: () => void;
}

const CORE: Readonly<Record<string, { key: string; icon: string }>> = {
  [CORE_ID.popOut]: { key: 'widgets.menu.pop_out', icon: 'external' },
  [CORE_ID.focusMain]: { key: 'opscenter.popout.focus_main', icon: 'arrow-out' },
  [CORE_ID.settings]: { key: 'widgets.menu.settings', icon: 'settings' },
  [CORE_ID.extendRow]: { key: 'widgets.menu.extend_row', icon: 'chevron-down' },
  [CORE_ID.pullBackRow]: { key: 'widgets.menu.pull_back_row', icon: 'chevron-up' },
  [CORE_ID.moveUp]: { key: 'widgets.menu.move_up', icon: 'chevron-up' },
  [CORE_ID.moveDown]: { key: 'widgets.menu.move_down', icon: 'chevron-down' },
  [CORE_ID.moveToDrawer]: { key: 'widgets.menu.move_to_drawer', icon: 'chevron-right' },
  [CORE_ID.moveToBar]: { key: 'widgets.menu.move_to_bar', icon: 'chevron-right' },
  [CORE_ID.editLayout]: { key: 'widgets.menu.edit_layout', icon: 'layout' },
  [CORE_ID.doneEditing]: { key: 'widgets.menu.done_editing', icon: 'layout' },
  [CORE_ID.closeWidget]: { key: 'widgets.menu.close', icon: 'close' },
  [CORE_ID.removeWidget]: { key: 'widgets.menu.remove', icon: 'close' },
  [CORE_ID.closeTab]: { key: 'widgets.menu.close_tab', icon: 'close' },
  [CORE_ID.moveTab]: { key: 'widgets.menu.move_tab', icon: 'chevron-right' },
  [CORE_ID.splitRight]: { key: 'widgets.menu.split_right', icon: 'chevron-right' },
  [CORE_ID.splitDown]: { key: 'widgets.menu.split_down', icon: 'chevron-down' },
};

export const BAR_SIZE_ORDER: readonly BarSize[] = ['compact', 'cozy', 'detailed'];

export const barSizeId = (size: BarSize): string => `bar-size-${size}`;

export function staysOpen(node: MenuNode): boolean {
  return node.keepOpen ?? (node.toggle === true && node.checked !== undefined);
}

export function closing(nodes: readonly MenuNode[], onClose: () => void): MenuNode[] {
  return nodes.map((node) => {
    if (node.children) return { ...node, children: closing(node.children, onClose) };
    const run = node.run;
    if (!run || staysOpen(node)) return { ...node };
    return {
      ...node,
      run: () => {
        try {
          run();
        } finally {
          onClose();
        }
      },
    };
  });
}

function core(id: string, run: () => void, extras: Partial<MenuNode> = {}): MenuNode {
  const look = CORE[id]!;
  return { id, label: t(look.key), icon: look.icon, run, ...extras };
}

function tabNodes(items: TabItems | null | undefined): MenuNode[] {
  if (!items) return [];
  return [
    ...(items.moveTo ? [core(CORE_ID.moveTab, items.moveTo)] : []),
    ...(items.splitRight ? [core(CORE_ID.splitRight, items.splitRight)] : []),
    ...(items.splitDown ? [core(CORE_ID.splitDown, items.splitDown)] : []),
    core(CORE_ID.closeTab, items.close, { danger: true }),
  ];
}

function arrangeNodes(entries: readonly ArrangeEntry[]): MenuNode[] {
  return entries.map((entry) => {
    const id = CORE_ID[entry.item];
    return core(id, entry.run, {
      ...(entry.label ? { label: entry.label } : {}),
      ...(entry.blocked ? { blocked: entry.blocked } : {}),
    });
  });
}

export function barSizeNodes(current: BarSize, set: (size: BarSize) => void): MenuNode[] {
  return BAR_SIZE_ORDER.map((size) => ({ id: barSizeId(size), label: t(`widget_bars.size.${size}`), checked: size === current, run: () => set(size) }));
}

export function joinGroups(groups: readonly (readonly MenuNode[])[]): MenuNode[] {
  const out: MenuNode[] = [];
  for (const group of groups) {
    group.forEach((node, at) => out.push({ ...node, sep: at === 0 && out.length > 0 ? true : undefined }));
  }
  return out;
}

let previewOnlyIds: ReadonlySet<string> | null = null;

export function setMenuPreviewOnly(ids: readonly string[] | null): void {
  previewOnlyIds = ids ? new Set(ids) : null;
}

function refusePreviewOnly(nodes: MenuNode[]): MenuNode[] {
  if (!previewOnlyIds) return nodes;
  const refused = previewOnlyIds;
  return nodes.map((node) => {
    if (node.children) return { ...node, children: refusePreviewOnly(node.children) };
    if (!refused.has(node.id)) return node;
    return { ...node, run: undefined, blocked: t('widgets.menu.preview_only'), title: t('widgets.menu.preview_only') };
  });
}

export function buildWidgetMenu(ctx: WidgetMenuCtx): MenuNode[] {
  const { editing } = ctx;
  const header: MenuNode[] = ctx.header
    ? [{ id: CORE_ID.showHeader, label: t('widgets.menu.show_header'), checked: ctx.header.shown, toggle: true, run: ctx.header.toggle }]
    : [];
  const layout: MenuNode[] = ctx.editLayout ? [core(editing ? CORE_ID.doneEditing : CORE_ID.editLayout, ctx.editLayout)] : [];
  const close: MenuNode[] = ctx.close
    ? [core(ctx.close.instance ? CORE_ID.removeWidget : CORE_ID.closeWidget, ctx.close.run, { danger: true })]
    : [];
  const rowNodes = arrangeNodes((ctx.arrange ?? []).filter((e) => e.item === 'extendRow' || (e.item === 'pullBackRow' && !e.blocked)));
  const windowGroup: MenuNode[] = [
    ...(ctx.popOut ? [core(CORE_ID.popOut, ctx.popOut)] : []),
    ...(ctx.focusMain ? [core(CORE_ID.focusMain, ctx.focusMain)] : []),
    ...header,
  ];
  const groups: (readonly MenuNode[])[] = [
    ...(ctx.content ?? []),
    ctx.scopeViews ?? [],
    ...(editing ? [ctx.views ?? [], header, ...(ctx.settings ?? []), arrangeNodes(ctx.arrange ?? [])] : [rowNodes, windowGroup]),
    tabNodes(ctx.tab),
    layout,
    close,
  ];
  return refusePreviewOnly(closing(joinGroups(groups), ctx.onClose));
}
