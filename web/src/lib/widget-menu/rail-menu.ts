/* the widget menu */
import type { MenuNode } from '../drawer-tabs/add-component-menu';
import { layoutNode, pinStripNode } from './bar-menu';
import { closing, joinGroups } from './model';
import { t } from '../i18n/index.svelte';

export interface RailMenuInput {
  pin?: { pinned: boolean; toggle: () => void } | null;
  openDrawer?: (() => void) | null;
  editing: boolean;
  toggleEdit: (() => void) | null;
  declared?: readonly (readonly MenuNode[])[];
  close?: { label: string; run: () => void } | null;
  onClose: () => void;
}

export function railMenuNodes(input: RailMenuInput): MenuNode[] {
  return closing(
    joinGroups([
      ...(input.declared ?? []),
      input.pin ? [pinStripNode(input.pin.pinned, input.pin.toggle, { pin: t('sidebar.rail.menu.pin'), unpin: t('sidebar.rail.menu.unpin') })] : [],
      input.openDrawer ? [{ id: 'open-drawer', label: t('sidebar.rail.menu.open_drawer'), icon: 'chevron-right', run: input.openDrawer }] : [],
      input.toggleEdit ? [layoutNode(input.editing, input.toggleEdit)] : [],
      input.close ? [{ id: 'close-tab', label: input.close.label, icon: 'close', run: input.close.run, danger: true }] : [],
    ]),
    input.onClose,
  );
}
