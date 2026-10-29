import { SKILL_KEYS, refusalMessage } from '../../../../client/js/labels/skill.js';
import type { CatalogHost } from '../catalog/catalog';
import ConfirmSheet from '../catalog/ConfirmSheet.svelte';
import { ledgerFailure, uninstallSheet } from '../catalog/installed-actions';
import type { InstalledItem } from '../catalog/types';
import { openModal } from '../modal';
import type { Translate } from '../sessions/types';

export function uninstallableRow(rows: readonly InstalledItem[], itemId: string): InstalledItem | undefined {
    return rows.find(
        (row) => row.item_id === itemId && row.kind === 'cplug' && row.source_index_url !== 'builtin' && typeof row.install_id === 'string' && row.install_id !== '',
    );
}

export async function uninstallPlugin(
    row: InstalledItem,
    name: string,
    host: Pick<CatalogHost, 'uninstall'>,
    t: Translate,
): Promise<{ done: boolean; error: string | null }> {
    const agreed = await openModal(ConfirmSheet as never, uninstallSheet(name, row, t) as never);
    if (!agreed || !row.install_id) return { done: false, error: null };
    try {
        await host.uninstall(row.install_id);
        return { done: true, error: null };
    } catch (error) {
        const outcome = ledgerFailure(error);
        if (outcome.kind === 'unsupported') return { done: false, error: t(SKILL_KEYS.refusedUnsupported) };
        return { done: false, error: refusalMessage(outcome.kind === 'refused' ? outcome.code : '', t) };
    }
}
