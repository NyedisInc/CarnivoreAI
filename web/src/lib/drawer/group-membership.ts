
import { EMPTY_CONTEXT, matches, type GroupRule, type RuleContext } from './group-rule';

export interface MembershipGroup {
    group_uuid: string;
    rule?: GroupRule | null;
    members?: string[];
    member_session_uuids?: string[];
}

export interface IdentityRow {
    name?: string;
    session_uuid?: string | null;
}

let byName = new Map<string, string>();
let byUuid = new Map<string, string>();
let nameRank = new Map<string, number>();
let uuidRank = new Map<string, number>();
let identities = new Map<string, string>();
let ruled: Array<{ uuid: string; rule: GroupRule }> = [];
let listed = new Map<string, Record<string, unknown>>();
let ruleContext: RuleContext = EMPTY_CONTEXT;

const rowListeners = new Set<() => void>();

export function subscribeRows(cb: () => void): () => void {
    rowListeners.add(cb);
    return () => { rowListeners.delete(cb); };
}

export function setRuleContext(ctx: RuleContext): void {
    ruleContext = ctx;
}

export function clear(): void {
    byName = new Map();
    byUuid = new Map();
    nameRank = new Map();
    uuidRank = new Map();
    ruled = [];
}

export function rebuild(groups: readonly MembershipGroup[]): void {
    clear();
    for (const g of groups || []) {
        if (g.rule) ruled.push({ uuid: g.group_uuid, rule: g.rule });
        (g.members || []).forEach((name, i) => {
            byName.set(name, g.group_uuid);
            nameRank.set(name, i);
        });
        (g.member_session_uuids || []).forEach((u, i) => {
            byUuid.set(u, g.group_uuid);
            uuidRank.set(u, i);
            if (typeof u === 'string' && u.indexOf('layout:') === 0) {
                byName.set(u, g.group_uuid);
                nameRank.set(u, i);
            }
        });
    }
}

export function setIdentities(rows: readonly IdentityRow[]): void {
    identities = new Map();
    listed = new Map();
    for (const row of Array.isArray(rows) ? rows : []) {
        if (row && row.name) listed.set(row.name, row as Record<string, unknown>);
        if (row && row.name && row.session_uuid) identities.set(row.name, row.session_uuid);
    }
    rowListeners.forEach((cb) => cb());
}

export function uuidOfName(name: string): string | null {
    return identities.get(name) || null;
}

function keyedByUuid(name: string): boolean {
    return !!identities.get(name) && byUuid.size > 0;
}

export function groupOf(name: string): string | null {
    const hit = keyedByUuid(name) ? byUuid.get(identities.get(name) as string) : byName.get(name);
    return hit === undefined ? ruledGroupOf(name) : hit;
}

function ruledGroupOf(name: string): string | null {
    const row = listed.get(name);
    if (!row || ruled.length === 0) return null;
    const hit = ruled.find((g) => matches(g.rule, row, ruleContext));
    return hit ? hit.uuid : null;
}

export function countMatching(rule: GroupRule): number {
    let n = 0;
    for (const row of listed.values()) if (matches(rule, row, ruleContext)) n += 1;
    return n;
}

export function memberRank(name: string): number | null {
    const uuid = keyedByUuid(name);
    const map = uuid ? uuidRank : nameRank;
    const key = uuid ? identities.get(name) as string : name;
    return map.has(key) ? map.get(key) as number : null;
}

export function setLocal(name: string, groupUuid: string | null): void {
    const sessionUuid = identities.get(name);
    if (groupUuid) byName.set(name, groupUuid);
    else byName.delete(name);
    if (sessionUuid) {
        if (groupUuid) byUuid.set(sessionUuid, groupUuid);
        else byUuid.delete(sessionUuid);
    }
}
