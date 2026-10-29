import * as G from './group-store';
import * as S from './store';
import { drawerEnv } from './env';

interface OrderGlobals {
    API?: { reorderSessionGroupMembers?(groupUuid: string, order: string[]): Promise<unknown> };
    SessionSidebarGroupActions?: { refresh?(): unknown };
}

export function nextOrder(visibleUuids: readonly string[], stored: readonly string[] | undefined): string[] {
    const seen = new Set(visibleUuids);
    return visibleUuids.concat((stored || []).filter((u) => !seen.has(u)));
}

/* not usable */
export async function commitMemberOrder(name: string): Promise<boolean> {
    const gl = drawerEnv() as OrderGlobals;
    const api = gl.API;
    if (!G.isUsable() || !api || typeof api.reorderSessionGroupMembers !== 'function') return false;
    if (S.isPinned(name)) return false;
    const groupUuid = G.groupOf(name);
    const group = G.groupByUuid(groupUuid);
    if (!group || !groupUuid) return false;
    const key = G.bandKeyFor(groupUuid);
    const names = Array.from(document.querySelectorAll<HTMLElement>(
        `#session-sidebar-list .session-sidebar-group[data-group="${key}"] .session-sidebar-row`,
    )).map((el) => el.dataset.name || '');
    const uuids = names.map((n) => G.uuidOfName(n));
    if (!uuids.length || uuids.some((u) => !u)) return false;
    const stored = group.member_session_uuids || [];
    const next = nextOrder(uuids as string[], stored);
    if (next.length === stored.length && next.every((u, i) => u === stored[i])) return false;
    try {
        G.apply(await api.reorderSessionGroupMembers(groupUuid, next));
        return true;
    } catch (err) {
        console.warn('SessionSidebarGroupOrder: member order not saved:', (err as Error)?.message);
        const actions = gl.SessionSidebarGroupActions;
        if (actions && typeof actions.refresh === 'function') actions.refresh();
        return false;
    }
}
