/* offloaded to the backup vault */
import { buttonAttrs, tagClass } from '../base/classes';
import { t } from '../i18n/index.svelte';
import type { SidebarRow } from './legacy';
import type { RowChipSpec, TextChip } from './row-plan';

export const RESTORE_ATTR = 'data-restore-offloaded';

export function offloadedTag(r: SidebarRow): TextChip | null {
    if (r.asleep !== true || r.offloaded !== true) return null;
    return { attrs: { class: tagClass('neutral'), 'data-tag': 'offloaded', title: t('sidebar.row.offloaded.title') }, text: t('projects.page.disk.offloaded') };
}

export function restoreButton(r: SidebarRow, name: string): RowChipSpec | null {
    const uuid = typeof r.session_uuid === 'string' ? r.session_uuid : '';
    if (r.asleep !== true || r.offloaded !== true || !uuid) return null;
    const label = t('sidebar.row.offloaded.restore_aria', { name });
    return {
        attrs: { type: 'button', ...buttonAttrs('secondary', 'sm'), [RESTORE_ATTR]: uuid, 'aria-label': label, title: label },
        text: t('sidebar.row.offloaded.restore'),
    };
}

/* nothing at all */
export function offloadedPart(r: SidebarRow, name: string): { offloaded?: TextChip; restore?: RowChipSpec } {
    const tag = offloadedTag(r);
    const restore = restoreButton(r, name);
    return { ...(tag ? { offloaded: tag } : {}), ...(restore ? { restore } : {}) };
}
