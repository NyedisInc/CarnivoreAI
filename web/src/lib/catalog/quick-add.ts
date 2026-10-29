import type { CatalogHost } from './catalog';
import { refusalCodeOf } from './install-actions';
import type { InstallScope, InstalledItem } from './types';

export type QuickAddOutcome =
    | { outcome: 'installed'; row: InstalledItem }
    | { outcome: 'sheet'; prefill: { scope: InstallScope; projectPath: string | null } }
    | { outcome: 'refused'; code: string };

export async function quickAdd(
    host: CatalogHost,
    itemId: string,
    target: InstallScope,
    projectPath: string | null,
): Promise<QuickAddOutcome> {
    const prefill = { scope: target, projectPath: target === 'project' ? projectPath : null };
    if (target === 'project' && !projectPath) return { outcome: 'sheet', prefill };
    try {
        const row = await host.install({
            item_id: itemId,
            scope: target,
            ...(target === 'project' ? { project_path: projectPath } : {}),
            one_click: true,
        });
        return { outcome: 'installed', row };
    } catch (error) {
        const code = refusalCodeOf(error);
        if (code === 'sheet_required') return { outcome: 'sheet', prefill };
        return { outcome: 'refused', code: code ?? '' };
    }
}
