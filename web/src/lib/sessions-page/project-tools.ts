import type { MenuItem } from '../projects-shared/ledger-model';

export const PROJECT_SETTINGS = 'project-settings';
export const PROJECT_PANEL = 'project-panel:';

export type ProjectTool = { readonly kind: 'settings' } | { readonly kind: 'panel'; readonly panelId: string };

export function withProjectTools(items: readonly MenuItem[], panels: readonly { readonly id: string; readonly labelKey: string }[]): readonly MenuItem[] {
    const tools: MenuItem[] = [
        { id: PROJECT_SETTINGS, labelKey: 'sessions.page.action.project_settings', sep: true },
        ...panels.map((panel) => ({ id: `${PROJECT_PANEL}${panel.id}`, labelKey: panel.labelKey })),
    ];
    const at = items.findIndex((i) => ['pack-folder', 'unpack-folder', 'unarchive-project', 'archive-project', 'delete-project'].includes(i.id));
    return at < 0 ? [...items, ...tools] : [...items.slice(0, at), ...tools, ...items.slice(at)];
}

export function toolOf(id: string): ProjectTool | null {
    if (id === PROJECT_SETTINGS) return { kind: 'settings' };
    return id.startsWith(PROJECT_PANEL) ? { kind: 'panel', panelId: id.slice(PROJECT_PANEL.length) } : null;
}
