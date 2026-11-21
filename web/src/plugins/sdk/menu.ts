import type { MenuNode } from '../../lib/drawer-tabs/add-component-menu';
import { closeItemMenu, itemMenuState, openItemMenu } from '../../lib/item-menu/open.svelte';
import { forwardMenuKey, rightClickMenu } from '../../lib/item-menu/page-row';

export { forwardMenuKey };

export interface PluginMenu {
  label: string;
  nodes: MenuNode[];
}

export function openMenu(menu: PluginMenu, anchor: Element): boolean {
  if (itemMenuState.open?.anchor === anchor) { closeItemMenu(); return false; }
  return openItemMenu('pagerow', menu, anchor);
}

export function menuRightClick(source: () => PluginMenu | null): Record<string, (event: never) => void> {
  return rightClickMenu(() => {
    const menu = source();
    return menu ? { type: 'pagerow', ctx: menu } : null;
  });
}
