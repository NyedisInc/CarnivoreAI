import type { ArrangementState } from '../drawer/store';
import type { ListingVerdict } from '../drawer/listing-state';
import type { Band, ProjectBucket as DrawerProjectBucket } from '../drawer/bucketing';

export type { ArrangementState, ListingVerdict };

export interface SidebarRow {
    name: string;
    kind?: string;
    is_pinned?: boolean;
    project_id?: number | null;
    project_name?: string | null;
    [field: string]: unknown;
}

export type BandBucket = Band<SidebarRow>;

export type ProjectBucket = DrawerProjectBucket<SidebarRow>;

export interface GroupsModule {
    chevronHtml?(): string;
}

export interface LayoutsModule {
    bandRows(rows: SidebarRow[]): { label: string; rows: SidebarRow[] } | null;
}

export interface ProjectHeaderModule {
    ledHtml(rows: SidebarRow[], collapsed: boolean, showLight?: boolean): string;
    iconHtml(name: string | null): string;
    iconForBand(key: string, isProject?: boolean): string | null;
    pickedIconHtml?(o: { key: string; bandKind: string }): string;
}

export interface LegacyDrawer {
    groups?: GroupsModule;
    layouts?: LayoutsModule;
    projectHeader?: ProjectHeaderModule;
    groupColour?: { attrsFor(key: string): string; groupFxHtml?(key: string, text: string): string };
    subagents?: { rollupHtml(rows: SidebarRow[]): string };
    i18n?: { t(key: string, params?: Record<string, unknown>): string };
}

interface LegacyGlobals {
    SessionSidebarGroups?: GroupsModule;
    SessionSidebarLayouts?: LayoutsModule;
    SessionSidebarProjectHeader?: ProjectHeaderModule;
    SessionSidebarGroupColour?: LegacyDrawer['groupColour'];
    SessionSidebarSubagents?: LegacyDrawer['subagents'];
    CloudeI18n?: LegacyDrawer['i18n'];
}

export function legacyDrawer(host: unknown = globalThis): LegacyDrawer {
    const g = host as LegacyGlobals;
    return {
        groups: g.SessionSidebarGroups,
        layouts: g.SessionSidebarLayouts,
        projectHeader: g.SessionSidebarProjectHeader,
        groupColour: g.SessionSidebarGroupColour,
        subagents: g.SessionSidebarSubagents,
        i18n: g.CloudeI18n,
    };
}
