import type { MenuNode } from '../drawer-tabs/add-component-menu';
import type { Translate } from '../sessions/types';
import type { MenuItem } from './ledger-model';

export function menuNodes(items: readonly MenuItem[], t: Translate, onPick: (id: string) => void): MenuNode[] {
    return items.map((item): MenuNode => {
        const label = item.label ?? t(item.labelKey ?? item.id);
        if (item.children) return { id: item.id, label, sep: item.sep, children: menuNodes(item.children, t, onPick) };
        return { id: item.id, label, sep: item.sep, checked: item.checked, run: () => onPick(item.id) };
    });
}
