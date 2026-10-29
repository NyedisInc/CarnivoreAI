import type { MenuNode } from '../../../lib/drawer-tabs/add-component-menu';
import type { DeclaredAction } from './declared-actions.svelte';
import { t } from '../../../lib/i18n/index.svelte';

export function menuLeaves(nodes: readonly MenuNode[]): MenuNode[] {
  return nodes.flatMap((node) => (node.children ? menuLeaves(node.children) : node.run ? [node] : []));
}

export function menuActions(
  nodes: readonly MenuNode[],
  prefix: string,
  label: (node: MenuNode) => string,
): DeclaredAction[] {
  return menuLeaves(nodes).map((node) => ({
    id: `${prefix}${node.id}`,
    label: label(node),
    ...(node.checked === undefined ? {} : { checked: node.checked }),
    ...(node.blocked ? { blocked: node.blocked } : {}),
    run: node.run!,
  }));
}

export function sortActions(menu: readonly MenuNode[]): DeclaredAction[] {
  return menuActions(menu, 'sort:', (node) => t('widgets.menu.sort_by', { name: node.label }));
}
