import type { MenuNode } from '../drawer-tabs/add-component-menu';
import type { Translate } from '../sessions/types';

export type RowMenuAction = 'open' | 'check' | 'withdraw';

export interface RowMenuState {
    canCheck: boolean;
    canWithdraw: boolean;
}

const ICONS: Record<RowMenuAction, string> = { open: 'eye', check: 'check', withdraw: 'trash' };

export function rowMenuNodes(state: RowMenuState, t: Translate, onPick: (action: RowMenuAction) => void): MenuNode[] {
    const blocked: Record<RowMenuAction, string | undefined> = {
        open: undefined,
        check: state.canCheck ? undefined : t('publish.page.menu.blocked_waiting'),
        withdraw: state.canWithdraw ? undefined : t('publish.page.menu.blocked_not_open'),
    };
    return (['open', 'check', 'withdraw'] as const).map((action): MenuNode => ({
        id: action,
        label: t(`publish.page.menu.${action}`),
        icon: ICONS[action],
        danger: action === 'withdraw' || undefined,
        sep: action === 'withdraw' || undefined,
        blocked: blocked[action],
        run: () => onPick(action),
    }));
}
