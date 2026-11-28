export const PROJECT_SETTINGS = 'project-settings';
export const PROJECT_PANEL = 'project-panel:';
export const PROJECT_SLOT_PANEL = 'project-slot-panel:';

export type ProjectTool =
    | { readonly kind: 'settings' }
    | { readonly kind: 'panel'; readonly panelId: string }
    | { readonly kind: 'slot-panel'; readonly pluginId: string; readonly entryId: string };

export function slotPanelMenuId(pluginId: string, entryId: string): string {
    return `${PROJECT_SLOT_PANEL}${encodeURIComponent(pluginId)}:${encodeURIComponent(entryId)}`;
}

export function toolOf(id: string): ProjectTool | null {
    if (id === PROJECT_SETTINGS) return { kind: 'settings' };
    if (id.startsWith(PROJECT_PANEL)) return { kind: 'panel', panelId: id.slice(PROJECT_PANEL.length) };
    if (id.startsWith(PROJECT_SLOT_PANEL)) {
        const rest = id.slice(PROJECT_SLOT_PANEL.length);
        const sep = rest.indexOf(':');
        if (sep <= 0) return null;
        try {
            return {
                kind: 'slot-panel',
                pluginId: decodeURIComponent(rest.slice(0, sep)),
                entryId: decodeURIComponent(rest.slice(sep + 1)),
            };
        } catch {
            return null;
        }
    }
    return null;
}
