import type { Component } from 'svelte';
import { ensurePanel, panelInstance, unmountPanel } from '../mount';
import AttributionPrompt from './AttributionPrompt.svelte';
import RecentSessions from './RecentSessions.svelte';
import ProjectTree from './ProjectTree.svelte';
import RunningSessions from './RunningSessions.svelte';

export interface PanelEntry {
    id: string;
    component: Component<Record<string, never>, Record<string, unknown>>;
}

export const LAUNCHPAD_PANELS: readonly PanelEntry[] = [
    { id: 'attribution-prompt', component: AttributionPrompt as PanelEntry['component'] },
    { id: 'running-sessions-list', component: RunningSessions as PanelEntry['component'] },
    { id: 'recent-sessions-list', component: RecentSessions as PanelEntry['component'] },
    { id: 'project-list', component: ProjectTree as PanelEntry['component'] },
];

export function mountLaunchpadPanels(): string[] {
    const mounted: string[] = [];
    for (const panel of LAUNCHPAD_PANELS) {
        if (ensurePanel(panel.id, panel.component, {})) mounted.push(panel.id);
    }
    return mounted;
}

export function unmountLaunchpadPanels(): number {
    let count = 0;
    for (const panel of LAUNCHPAD_PANELS) {
        if (unmountPanel(panel.id)) count += 1;
    }
    return count;
}

export function refreshLaunchpadPanels(): string[] {
    const asked: string[] = [];
    for (const panel of LAUNCHPAD_PANELS) {
        const instance = panelInstance(panel.id);
        const refresh = instance?.refresh;
        if (typeof refresh !== 'function') continue;
        try {
            void (refresh as () => unknown)();
            asked.push(panel.id);
        } catch (error) {
            console.error('CloudeWeb: panel refresh failed for', panel.id, error);
        }
    }
    return asked;
}
