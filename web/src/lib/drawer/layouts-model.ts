import { t } from '../i18n/index.svelte';
import { drawerEnv } from './env';
import { isCollapsed } from './store';
import { filterActive } from './search';

export const PREFIX = 'layout:';

export interface LayoutMemberRef { session_uuid?: string }

export interface BridgeLayout {
    layout_uuid: string;
    name: string;
    colour: string;
    gradient: string | null;
    animation: string;
    created_at: string;
    members?: LayoutMemberRef[];
}

export interface LayoutsBridge {
    list(): BridgeLayout[];
    get(uuid: string): BridgeLayout | null;
    setStyle(uuid: string, style: { colour: string | null; gradient: string | null; animation: string | null }): Promise<unknown>;
    rename(uuid: string, name: string): Promise<unknown>;
    delete(uuid: string): Promise<void>;
    reorder(order: string[]): Promise<unknown>;
}

export interface MemberRow { session_uuid?: string; name?: string; label?: string; [key: string]: unknown }

export interface LayoutRow {
    name: string;
    kind: 'layout';
    layout_uuid: string;
    label: string;
    colour: string;
    gradient: string | null;
    animation: string;
    member_count: number;
    member_names: string[];
    _members: MemberRow[];
    created_at_epoch: number;
    last_work_at: null;
    project_id: null;
    project_name: null;
    working_dir: null;
    is_pinned?: boolean;
}

export function bridge(): LayoutsBridge | null {
    const layouts = drawerEnv().CloudeWeb?.layouts as LayoutsBridge | undefined;
    return layouts && typeof layouts.list === 'function' ? layouts : null;
}

export function isLayoutName(name: unknown): boolean {
    return typeof name === 'string' && name.indexOf(PREFIX) === 0;
}

export function idOf(name: unknown): string {
    return isLayoutName(name) ? (name as string).slice(PREFIX.length) : '';
}

export function isOpenLayout(row: { layout_uuid: string }): boolean {
    const page = drawerEnv().CloudeWeb?.layoutPage as { current?(): { uuid?: string } | null } | undefined;
    const current = page && typeof page.current === 'function' ? page.current() : null;
    return !!(current && current.uuid === row.layout_uuid);
}

function memberRows(layout: BridgeLayout, allRows: unknown): MemberRow[] {
    const byUuid = new Map<string, MemberRow>();
    for (const r of Array.isArray(allRows) ? (allRows as MemberRow[]) : []) {
        if (r && r.session_uuid) byUuid.set(r.session_uuid, r);
    }
    const members = Array.isArray(layout.members) ? layout.members : [];
    return members.map((m) => (m.session_uuid ? byUuid.get(m.session_uuid) : undefined)).filter((r): r is MemberRow => !!r);
}

export function rows(allRows: unknown): LayoutRow[] {
    const b = bridge();
    if (!b) return [];
    const label = drawerEnv().SessionLabel as { resolve?(r: MemberRow): string } | undefined;
    return b.list().map((L) => {
        const members = memberRows(L, allRows);
        return {
            name: PREFIX + L.layout_uuid,
            kind: 'layout' as const,
            layout_uuid: L.layout_uuid,
            label: L.name,
            colour: L.colour, gradient: L.gradient, animation: L.animation,
            member_count: Array.isArray(L.members) ? L.members.length : 0,
            member_names: members.map((r) => (label ? (label.resolve?.(r) || r.name || '') : (r.label || r.name || ''))),
            _members: members,
            created_at_epoch: Date.parse(L.created_at) / 1000 || 0,
            last_work_at: null,
            project_id: null,
            project_name: null,
            working_dir: null,
        };
    });
}

export function memberUuids(): Set<string> {
    const out = new Set<string>();
    const b = bridge();
    for (const L of b ? b.list() : []) {
        for (const m of Array.isArray(L.members) ? L.members : []) if (m && m.session_uuid) out.add(m.session_uuid);
    }
    return out;
}

export function isExpanded(uuid: string): boolean {
    if (filterActive()) return true;
    return isCollapsed(PREFIX + uuid);
}

export interface MemberBody { bodyId: string; uuid: string; band: string; members: MemberRow[] }

export function memberBody(row: LayoutRow, band?: string): MemberBody | null {
    if (band !== 'layouts') return null;
    const expanded = isExpanded(row.layout_uuid);
    return {
        bodyId: `session-sidebar-layout-body-${row.layout_uuid}`,
        uuid: row.layout_uuid,
        band: PREFIX + row.layout_uuid,
        members: expanded && Array.isArray(row._members) ? row._members : [],
    };
}

export function bandRows(allRows: unknown): { label: string; rows: LayoutRow[] } | null {
    const b = bridge();
    if (!b) return null;
    const byName = new Map<string, LayoutRow>();
    for (const r of Array.isArray(allRows) ? (allRows as Array<LayoutRow | null>) : []) {
        if (r && r.kind === 'layout') byName.set(r.name, r);
    }
    const list = b.list().map((L) => byName.get(PREFIX + L.layout_uuid)).filter((r): r is LayoutRow => !!r);
    return list.length ? { label: t('layout.section.heading'), rows: list } : null;
}

export function activate(_ctrl: unknown, name: string): boolean {
    if (!isLayoutName(name)) return false;
    const page = drawerEnv().CloudeWeb?.layoutPage as { openLayout?(uuid: string): void } | undefined;
    if (page && typeof page.openLayout === 'function') page.openLayout(idOf(name));
    else window.location.assign(`/layout/${encodeURIComponent(idOf(name))}`);
    return true;
}

export function rename(uuid: string, name: string): Promise<unknown> {
    const b = bridge();
    return b ? b.rename(uuid, name) : Promise.reject(new Error('the layouts module is not loaded'));
}

export function blueprintsEnabled(): boolean {
    const bp = drawerEnv().CloudeWeb?.blueprints as { fromLayout?: unknown } | undefined;
    return !!(bp && typeof bp.fromLayout === 'function');
}
