import type { SidebarRow } from './legacy';
import * as GroupStoreModule from '../drawer/group-store';
import { drawerEnv } from '../drawer/env';
import { t } from '../i18n/index.svelte';

export interface SessionGroup {
    group_uuid: string;
    name: string;
    members: string[];
    colour?: string | null;
    gradient?: string | null;
    animation?: string | null;
    icon?: string | null;
}

export interface GroupsBody {
    status?: string;
    groups?: SessionGroup[];
    freed?: number;
    [field: string]: unknown;
}

export interface GroupStore {
    isUsable(): boolean;
    current(): { status: string; groups: SessionGroup[] };
    apply(body: unknown): unknown;
    markUnavailable(detail: string): void;
    groupByUuid(uuid: string): SessionGroup | null;
    groupUuidOf(key: string): string | null;
    groupOf(name: string): string | null;
    projectBandKeyFor(projectId: unknown): string;
    toggleProjectsOpen(): boolean;
}

export interface ProjectRow {
    id: unknown;
    path?: string | null;
}

export interface HeadingApi {
    listSessionGroups(): Promise<GroupsBody>;
    createSessionGroup(name: string): Promise<GroupsBody>;
    assignSessionGroup(name: string, uuid: string | null): Promise<GroupsBody>;
    renameSessionGroup(uuid: string, name: string): Promise<GroupsBody>;
    reorderSessionGroups(order: string[]): Promise<GroupsBody>;
    deleteSessionGroup(uuid: string): Promise<GroupsBody>;
    setSessionGroupStyle(uuid: string, style: { colour: string; gradient: string | null; animation: string }): Promise<GroupsBody>;
    updateProject(name: string, o: { newName?: string; color?: string }): Promise<unknown>;
    archiveProject(name: string): Promise<unknown>;
    getProjects(): Promise<ProjectRow[]>;
    sleepSession(uuid: string): Promise<{ status?: string; detail?: string } | null>;
    destroySession(id: string): Promise<unknown>;
    destroyExternalSession(name: string): Promise<unknown>;
    deleteSessionRecord(uuid: string): Promise<unknown>;
}

export interface DrawerController {
    _rows?: SidebarRow[];
    repaint?(): void;
    _fetchAndRender?(): Promise<void>;
}

export interface HeadingGlobals {
    SessionSidebar?: DrawerController;
    SessionSidebarGroupColour?: { open(anchor: Element, uuid: string): void; openFull?(anchor: Element, kind: string, id: string): void };
    SessionSidebarGroupIcon?: { open(anchor: Element, uuid: string): void };
    SessionRowMenuIcons?: { svg(id: string, size?: number): string };
    SessionLabel?: {
        validate?(raw: string): { ok: boolean; value?: string; reason?: string };
        LABEL_MAX_CHARS?: number;
    };
    WriteFailureNotice?: { report?(text: string): void };
    API?: HeadingApi;
    App?: {
        showConfirmModal(
            title: string, message: string, detail: string,
            confirm: string, cancel: string, variant: string,
        ): Promise<boolean>;
    };
    CloudeWeb?: {
        openBlueprintsScreen?(): void;
        layouts?: {
            get?(uuid: string): { name: string; colour: string; gradient: string | null; animation: string } | null;
            setStyle?(uuid: string, style: { colour: string; gradient: string | null; animation: string }): Promise<unknown>;
        };
        launchpad?: { selectProject?(project: { name: string; path: string }, choice?: null): unknown };
        addToMenu?: {
            openForGroup?(
                anchor: HTMLElement, groupUuid: string,
                opts?: { parentEl?: HTMLElement | null; onFinish?: () => void },
            ): void;
        };
    };
}

export function hg(): HeadingGlobals {
    return drawerEnv() as HeadingGlobals;
}

export function usableGroups(): GroupStore | null {
    return GroupStoreModule.isUsable() ? GroupStoreModule as unknown as GroupStore : null;
}

export function announce(text: string): void {
    const region = document.getElementById('session-sidebar-live');
    if (region) region.textContent = text;
}

export function announceFailure(text: string): void {
    announce(text);
    const notice = hg().WriteFailureNotice;
    if (notice && typeof notice.report === 'function') notice.report(text);
}

export function reasonOf(err: unknown): string {
    const message = (err as { message?: string } | null)?.message;
    return message || String(err || t('error.server_unreachable'));
}

export function repaintDrawerRows(): void {
    const ctrl = hg().SessionSidebar;
    if (ctrl && typeof ctrl.repaint === 'function') ctrl.repaint();
}

export async function refetchDrawer(): Promise<void> {
    const ctrl = hg().SessionSidebar;
    if (ctrl && typeof ctrl._fetchAndRender === 'function') {
        await ctrl._fetchAndRender();
    }
}

export function applyGroups(body: GroupsBody): void {
    GroupStoreModule.apply(body);
    repaintDrawerRows();
}

export async function refreshGroups(): Promise<void> {
    const api = hg().API;
    if (!api) return;
    try {
        GroupStoreModule.apply(await api.listSessionGroups());
    } catch (err) {
        GroupStoreModule.markUnavailable(reasonOf(err));
    }
    repaintDrawerRows();
}
