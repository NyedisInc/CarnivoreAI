import type { Component } from 'svelte';
import type { AccountFeature } from '../carnivore-account/features';

export type PluginSurface =
    | 'session-card-action'
    | 'settings-panel';

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
    readonly kind?: string | null;
}

export interface SessionCardAction {
    label(row: SessionCardRow): string;
    run(row: SessionCardRow, context: PluginContext): void | Promise<void>;
    hidden?(row: SessionCardRow): boolean;
    readonly localOnly?: boolean;
    readonly requiresSessionUuid?: boolean;
}

export interface SettingsPanelPayload {
    readonly Panel: Component<Record<string, never>>;
}

export interface SurfacePayloads {
    'session-card-action': SessionCardAction;
    'settings-panel': SettingsPanelPayload;
}

export interface Contribution<K extends PluginSurface = PluginSurface> {
    readonly id: string;
    readonly surface: K;
    readonly order?: number;
    readonly feature?: AccountFeature;
    enabled(context: PluginContext): boolean;
    readonly payload: SurfacePayloads[K];
}

export interface Plugin {
    readonly id: string;
    readonly contributions: readonly Contribution[];
}

export type CplugPermissionRisk = 'low' | 'medium' | 'high' | 'never';

export interface CplugServiceProvidesDecl {
    readonly name: string;
    readonly methods: readonly string[];
    readonly schemas?: Readonly<Record<string, unknown>>;
}

export interface CplugServicesDecl {
    readonly provides?: readonly CplugServiceProvidesDecl[];
    readonly consumes?: readonly string[];
}

export interface CplugEventsDecl {
    readonly on?: readonly string[];
    readonly emit?: readonly string[];
    readonly allowed?: readonly string[];
}

export interface CplugChannelDecl {
    readonly id: string;
    readonly kind_id: string;
    readonly label?: string | null;
}

export interface CplugCommandDecl {
    readonly id: string;
    readonly title?: string;
    readonly label?: string;
    readonly shortcut?: string;
    readonly route?: string;
    readonly tool?: string;
    readonly macro?: string;
    readonly [key: string]: unknown;
}

export type CplugChordDecl =
    | string
    | {
          readonly command?: string | null;
          readonly shortcut?: string;
          readonly chord?: string;
          readonly route?: string;
          readonly tool?: string;
          readonly macro?: string;
      };

export interface CplugUiSlotRow {
    readonly slot: string;
    readonly count: number;
    readonly risk: CplugPermissionRisk;
    readonly reason: string;
    readonly granted: boolean;
    readonly needs_tick: boolean;
}

export interface PopoutConfigDecl {
    readonly enabled?: boolean;
    readonly width?: number;
    readonly height?: number;
    readonly multi?: boolean;
}

export interface SidebarTabDecl {
    readonly id?: string;
    readonly title?: string;
    readonly icon?: string;
    readonly popout?: boolean | PopoutConfigDecl;
    readonly mode?: string;
    readonly view?: string;
    readonly ui_file?: string;
    readonly document?: unknown;
    readonly multi?: boolean;
    readonly popout_multi?: boolean;
}

export interface SlotContribution {
    readonly plugin_id: string;
    readonly install_key: string;
    readonly slot: string;
    readonly declared_slot: string;
    readonly item: Record<string, unknown>;
}

export interface CplugSlotsResponse {
    readonly slots: Readonly<Record<string, readonly SlotContribution[]>>;
    readonly owners: Readonly<Record<string, string>>;
}
