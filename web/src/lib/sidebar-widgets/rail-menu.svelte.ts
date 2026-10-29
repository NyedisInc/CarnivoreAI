import { layoutEditor, toggleLayoutEditor } from '../../opscenter/layout-editor/editor.svelte';
import { canOpen } from '../../opscenter/layout-editor/empty-space-menu.svelte';
import { t } from '../i18n/index.svelte';
import type { MenuNode } from '../drawer-tabs/add-component-menu';
import { railMenuNodes } from '../widget-menu/rail-menu';
import { barPinned, stripPinsOffered, toggleBarPin } from '../widget-bars/bar-pin-action';
import { railEntries } from './rail-model';
import { declaredActionsFor } from '../../opscenter/widgets/menu/declared-actions.svelte';
import { declaredGroups } from '../widget-menu/declared-nodes';
import { rootZone, SESSION_LIST_TAB } from '../drawer-layout/root-zone.svelte';
import { SESSION_LIST_WIDGET } from './widget-ids';
import { isMenuKey } from '../zone-shell/key-nav';

export const railMenu: { at: { x: number; y: number } | null; keyId: string | null } = $state({ at: null, keyId: null });

export function closeRailMenu(): void {
  railMenu.at = null;
  railMenu.keyId = null;
}

function keyUnder(target: EventTarget | null): string | null {
  return target instanceof Element ? (target.closest<HTMLElement>('[data-rail-key]')?.dataset.railKey ?? null) : null;
}

export function onRailShellContextMenu(event: MouseEvent): void {
  if (event.defaultPrevented) return;
  event.preventDefault();
  openRailMenu(keyUnder(event.target), event.clientX, event.clientY);
}

function openRailMenu(keyId: string | null, x: number, y: number): void {
  railMenu.keyId = keyId;
  if (railMenuItems().length === 0) {
    closeRailMenu();
    return;
  }
  railMenu.at = { x, y };
}

export function onRailShellMenuKey(event: KeyboardEvent): void {
  if (!isMenuKey(event)) return;
  const at = event.target instanceof Element ? event.target.closest<HTMLElement>('[data-rail-key], [data-bar-handle]') : null;
  if (!at) return;
  event.preventDefault();
  const box = at.getBoundingClientRect();
  openRailMenu(at.dataset.railKey ?? null, box.right, box.top);
}

export function railNodesFor(keyId: string | null, onClose: () => void, declaredMore: readonly (readonly MenuNode[])[] = []): MenuNode[] {
  const entry = keyId ? [...railEntries().fixed, ...railEntries().registered].find((w) => w.id === keyId) : undefined;
  const closeTab = entry?.close;
  const root = rootZone();
  const declared = keyId === SESSION_LIST_WIDGET ? declaredGroups(declaredActionsFor(root.headerIdOf({ key: SESSION_LIST_TAB, kind: 'panel' }))) : [];
  return railMenuNodes({
    pin: keyId === null && stripPinsOffered() ? { pinned: barPinned('rail'), toggle: () => void toggleBarPin('rail') } : null,
    declared: [...declared, ...declaredMore],
    editing: layoutEditor.active,
    toggleEdit: canOpen() ? () => void toggleLayoutEditor() : null,
    close: entry && closeTab ? { label: t('sidebar.rail.menu.close_tab'), run: closeTab } : null,
    onClose,
  });
}

export function railMenuItems(): MenuNode[] {
  return railNodesFor(railMenu.keyId, closeRailMenu);
}
