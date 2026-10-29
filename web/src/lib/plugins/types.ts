/* the plugins page */
import type { Component } from 'svelte';
import type { AccountFeature } from '../carnivore-account/features';

export type PluginSurface =
    | 'session-card-action'
    | 'launchpad-panel'
    | 'sidebar-item'
    | 'status-source'
    | 'settings-panel'
    | 'session-tab';

/* could not */
export interface PluginContext {
    readonly flags: Readonly<Record<string, boolean>>;
    refresh(): void | Promise<void>;
}

export interface SessionCardRow {
    readonly name: string;
    readonly unread: boolean;
    readonly sessionId?: string | null;
    readonly hostKey?: string | null;
    readonly sessionUuid?: string | null;
    readonly projectId?: number | string | null;
}

/* <button role="menuitem"> role="button" */
export interface SessionCardAction {
    readonly shortcut: string;
    label(row: SessionCardRow): string;
    run(row: SessionCardRow, context: PluginContext): void | Promise<void>;
    hidden?(row: SessionCardRow): boolean;
}

export interface LaunchpadPanel {
    readonly containerId: string;
    readonly component: Component;
}

export interface SidebarItem {
    readonly label: string;
    readonly icon: string;
    run(context: PluginContext): void | Promise<void>;
}

export interface StatusSource {
    resolve(tmuxName: string): string | null;
}

export interface SettingsPanelPayload {
    readonly Panel: Component<Record<string, never>>;
}

export interface SessionTabSession {
    readonly session_uuid: string;
}

/* the contributions */
export interface SessionTabPayload {
    readonly labelKey: string;
    readonly Tab: Component<{ session: SessionTabSession }>;
}

export interface SurfacePayloads {
    'session-card-action': SessionCardAction;
    'launchpad-panel': LaunchpadPanel;
    'sidebar-item': SidebarItem;
    'status-source': StatusSource;
    'settings-panel': SettingsPanelPayload;
    'session-tab': SessionTabPayload;
}

export interface Contribution<K extends PluginSurface = PluginSurface> {
    readonly id: string;
    readonly surface: K;
    readonly order?: number;
    readonly feature?: AccountFeature;
    enabled(context: PluginContext): boolean;
    readonly payload: SurfacePayloads[K];
}

/* the contributions */
export interface Plugin {
    readonly id: string;
    readonly contributions: readonly Contribution[];
}
