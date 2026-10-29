import type { MenuNode } from '../drawer-tabs/add-component-menu';
import type { DeclaredAction } from '../../opscenter/widgets/menu/declared-actions.svelte';
import { isScopeSwitch } from '../../opscenter/widgets/views';
import type { WidgetMenuCtx } from '../widget-menu/model';
import { widgetMenuNodes } from '../item-menu/widget-nodes';
import { declaredGroups } from '../widget-menu/declared-nodes';
import { copyOptionNodes, lookNodes, settingNodes, type OptionNodesInput } from '../widget-menu/option-nodes';

export type MenuHost = 'bar-key' | 'section-head' | 'drawer-card' | 'glance' | 'popout' | 'tab' | 'grid' | 'right-drawer';

export const MENU_HOSTS: readonly MenuHost[] = ['bar-key', 'section-head', 'drawer-card', 'glance', 'popout', 'tab'];

export interface PlacementMenuInput
  extends Pick<WidgetMenuCtx, 'popOut' | 'focusMain' | 'header' | 'arrange' | 'editLayout' | 'close' | 'tab'> {
  host: MenuHost;
  editing: boolean;
  onClose: () => void;
  options: OptionNodesInput;
  declared: readonly DeclaredAction[];
  copyHeading?: string;
  copyTail?: readonly MenuNode[];
  lead?: readonly (readonly MenuNode[])[];
  settings?: readonly (readonly MenuNode[])[];
}

export function placementMenuCtx(input: PlacementMenuInput): WidgetMenuCtx {
  const { options } = input;
  const looks = input.host === 'grid' ? [] : lookNodes(options);
  return {
    editing: input.editing,
    onClose: input.onClose,
    content: [...(input.lead ?? []), [...copyOptionNodes(options, input.copyHeading), ...(input.copyTail ?? [])], ...declaredGroups(input.declared)].filter((group) => group.length > 0),
    ...(isScopeSwitch(options.manifest) ? { scopeViews: looks } : { views: looks }),
    settings: input.settings ?? settingNodes(options),
    popOut: input.popOut,
    focusMain: input.focusMain,
    header: input.header,
    arrange: input.arrange,
    editLayout: input.editLayout,
    close: input.close,
    tab: input.tab,
  };
}

export function placementMenu(input: PlacementMenuInput): MenuNode[] {
  return widgetMenuNodes(placementMenuCtx(input));
}
