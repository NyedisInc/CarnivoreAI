/* Escape cancels */
import { t } from '../i18n/index.svelte';
import { headingRename, openHeadingRename } from './heading-rename.svelte';
import { announce, hg } from './interaction-globals';
import { dataOf, refetch, rg } from './row-globals';

const ROW_KEY = 'row:';

export function rowRenameKey(name: string, band: string | null | undefined): string {
    return `${ROW_KEY}${name}|${band || ''}`;
}

export function isRowEditing(name: string, band: string | null | undefined): boolean {
    return headingRename.spec?.key === rowRenameKey(name, band);
}

export function beginRowRename(rowEl: Element): boolean {
    if (headingRename.spec || hg().SessionSidebarRename?.isEditing?.()) return false;
    const name = dataOf(rowEl, 'name');
    const id = dataOf(rowEl, 'sessionId') || (rowEl.hasAttribute('data-asleep') ? dataOf(rowEl, 'sessionUuid') : '') || dataOf(rowEl, 'browserId') || dataOf(rowEl, 'layoutUuid') || null;
    const nameEl = rowEl.querySelector('[data-row-name]');
    if (rowEl.getAttribute('data-rename-state') !== 'renameable' || !id || !name) {
        const note = nameEl ? nameEl.getAttribute('data-name-note') || '' : '';
        announce(note || t('sidebar.row.rename.refused'));
        rowEl.setAttribute('data-rename-refused', '1');
        return false;
    }
    if (!nameEl) return false;
    const seed = (nameEl.textContent || '').trim();
    return openHeadingRename({
        key: rowRenameKey(name, dataOf(rowEl, 'band')),
        seed,
        ariaLabel: `Rename ${seed}`,
        save: (value) => {
            const g = rg();
            const B = g.SessionSidebarBrowsers;
            const L = g.SessionSidebarLayouts;
            if (B?.isBrowserName?.(name) && B.rename) return B.rename(id, value);
            if (L?.isLayoutName?.(name) && L.rename) return L.rename(id, value);
            if (!g.API) return Promise.reject(new Error('the API client is not loaded'));
            return g.API.renameSession(id, value);
        },
        afterSuccess: async () => {
            const ctrl = rg().SessionSidebar;
            if (ctrl) await refetch(ctrl);
        },
    });
}
