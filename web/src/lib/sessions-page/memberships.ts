
export interface LayoutLike {
    readonly layout_uuid: string;
    readonly name: string;
    readonly members: ReadonlyArray<{ readonly session_uuid: string }>;
}

export interface GroupLike {
    readonly group_uuid: string;
    readonly name: string;
    readonly member_session_uuids: readonly string[];
}

export interface Belongs {
    readonly uuid: string;
    readonly name: string;
}

export interface Memberships {
    readonly layouts: readonly Belongs[];
    readonly groups: readonly Belongs[];
}

export const NONE: Memberships = { layouts: [], groups: [] };

export function membershipsOf(sessionUuid: string, layouts: readonly LayoutLike[], groups: readonly GroupLike[]): Memberships {
    if (!sessionUuid) return NONE;
    const inLayouts = layouts
        .filter((l) => l.members.some((m) => m.session_uuid === sessionUuid))
        .map((l): Belongs => ({ uuid: l.layout_uuid, name: l.name }));
    const group = groups.find((g) => g.member_session_uuids.includes(sessionUuid));
    const inGroups: Belongs[] = group ? [{ uuid: group.group_uuid, name: group.name }] : [];
    return inLayouts.length === 0 && inGroups.length === 0 ? NONE : { layouts: inLayouts, groups: inGroups };
}

export function isNone(m: Memberships): boolean {
    return m.layouts.length === 0 && m.groups.length === 0;
}
