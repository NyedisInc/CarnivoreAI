import { t } from '../i18n/index.svelte';
import type { SidebarRow } from './legacy';
import type { TextChip } from './row-plan';

export function closedChip(r: SidebarRow): TextChip | null {
    if (r.closed !== true) return null;
    return {
        attrs: { class: 'session-sidebar-row-badge session-sidebar-row-closed', title: t('session.closed.title') },
        text: t('session.closed.label'),
    };
}

/* nothing at all */
export function closedPart(r: SidebarRow): { closed?: TextChip } {
    const chip = closedChip(r);
    return chip ? { closed: chip } : {};
}
