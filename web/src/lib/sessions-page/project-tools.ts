export const PROJECT_SETTINGS = 'project-settings';
export const PROJECT_PANEL = 'project-panel:';

export type ProjectTool = { readonly kind: 'settings' } | { readonly kind: 'panel'; readonly panelId: string };

export function toolOf(id: string): ProjectTool | null {
    if (id === PROJECT_SETTINGS) return { kind: 'settings' };
    return id.startsWith(PROJECT_PANEL) ? { kind: 'panel', panelId: id.slice(PROJECT_PANEL.length) } : null;
}
