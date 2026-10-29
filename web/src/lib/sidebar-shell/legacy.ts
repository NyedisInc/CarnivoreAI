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

export interface LayoutsModule {
    bandRows(rows: SidebarRow[]): { label: string; rows: SidebarRow[] } | null;
}

import * as ProjectHeader from './project-header';

export interface ProjectHeaderModule {
    ledHtml(rows: SidebarRow[], collapsed: boolean, showLight?: boolean): string;
    iconHtml(name: string | null): string;
    iconForBand(key: string, isProject?: boolean): string | null;
    pickedIconHtml?(o: { key: string; bandKind: string }): string;
}

export interface LegacyDrawer {
    layouts?: LayoutsModule;
    projectHeader?: ProjectHeaderModule;
    groupColour?: { attrsFor(key: string): string; groupFxHtml?(key: string, text: string): string };
    i18n?: { t(key: string, params?: Record<string, unknown>): string };
}

interface LegacyGlobals {
    SessionSidebarLayouts?: LayoutsModule;
    SessionSidebarGroupColour?: LegacyDrawer['groupColour'];
    CloudeI18n?: LegacyDrawer['i18n'];
}

export function legacyDrawer(host: unknown = globalThis): LegacyDrawer {
    const g = host as LegacyGlobals;
    return {
        layouts: g.SessionSidebarLayouts,
        projectHeader: ProjectHeader,
        groupColour: g.SessionSidebarGroupColour,
        i18n: g.CloudeI18n,
    };
}
