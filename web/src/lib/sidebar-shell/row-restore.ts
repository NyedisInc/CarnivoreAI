import { promptRestore } from '../offload-prompt/offload-prompt';
import { dataOf, type RowController } from './row-globals';

const restoring = new Set<string>();

export async function restoreOffloadedRow(ctrl: RowController, button: Element, rowEl: Element | null): Promise<boolean> {
    const sessionUuid = button.getAttribute('data-restore-offloaded') || '';
    if (!sessionUuid || restoring.has(sessionUuid)) return false;
    const row = (ctrl.rows?.() ?? []).find((r) => r && r.session_uuid === sessionUuid);
    const label = (row?.label != null && String(row.label)) || (rowEl ? dataOf(rowEl, 'name') : '') || '';
    restoring.add(sessionUuid);
    try {
        const done = await promptRestore({ sessionUuid, label });
        if (done) await ctrl._fetchAndRender?.();
        return done;
    } finally {
        restoring.delete(sessionUuid);
    }
}
