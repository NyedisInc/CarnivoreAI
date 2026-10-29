import type { MenuNode } from '../drawer-tabs/add-component-menu';
import { t } from '../i18n/index.svelte';
import type { WidgetAreaState } from '../dynamic-tabs/types';
import type { BarSize } from '../widget-bars/bar-settings.svelte';
import { CORE_ID, barSizeNodes, closing, joinGroups } from './model';

export function layoutNode(editing: boolean, toggle: () => void): MenuNode {
  return {
    id: editing ? CORE_ID.doneEditing : CORE_ID.editLayout,
    label: t(editing ? 'widgets.menu.done_editing' : 'widgets.menu.edit_layout'),
    icon: 'layout',
    run: toggle,
  };
}

export function pinStripNode(
  pinned: boolean,
  toggle: () => void,
  words: { pin: string; unpin: string } = { pin: t('widget_bars.menu.pin'), unpin: t('widget_bars.menu.unpin') },
): MenuNode {
  return { id: 'pin-bar', label: pinned ? words.unpin : words.pin, run: toggle };
}

export interface BarMenuInput {
  size: BarSize;
  pinned: boolean;
  editing: boolean;
  setSize: (size: BarSize) => void;
  togglePin: (() => void) | null;
  toggleEdit: (() => void) | null;
  onClose: () => void;
}

export function barMenuNodes(input: BarMenuInput): MenuNode[] {
  return closing(
    joinGroups([
      barSizeNodes(input.size, input.setSize),
      input.togglePin ? [pinStripNode(input.pinned, input.togglePin)] : [],
      input.toggleEdit ? [layoutNode(input.editing, input.toggleEdit)] : [],
    ]),
    input.onClose,
  );
}

export interface AreaMenuInput {
  state: WidgetAreaState;
  editing: boolean;
  setState: (state: WidgetAreaState) => void;
  toggleEdit: (() => void) | null;
  onClose: () => void;
}

const AREA_STATES: readonly WidgetAreaState[] = ['closed', 'glance', 'full'];

export function areaMenuNodes(input: AreaMenuInput): MenuNode[] {
  return closing(
    joinGroups([
      AREA_STATES.map((state) => ({ id: `area-${state}`, label: t(`widget_area.state.${state}`), checked: state === input.state, run: () => input.setState(state) })),
      input.toggleEdit ? [layoutNode(input.editing, input.toggleEdit)] : [],
    ]),
    input.onClose,
  );
}
