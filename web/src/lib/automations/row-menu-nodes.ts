import type { MenuNode } from '../drawer-tabs/add-component-menu';
import { t } from '../i18n/index.svelte';

export type RowMenuAction = 'edit' | 'duplicate' | 'delete';

const ICONS: Record<RowMenuAction, string> = { edit: 'pencil', duplicate: 'copy', delete: 'trash' };

export function automationMenuNodes(onPick: (action: RowMenuAction) => void): MenuNode[] {
  return (['edit', 'duplicate', 'delete'] as const).map((action): MenuNode => ({
    id: action,
    label: t(`automations.page.menu.${action}`),
    icon: ICONS[action],
    danger: action === 'delete' || undefined,
    sep: action === 'delete' || undefined,
    run: () => onPick(action),
  }));
}
