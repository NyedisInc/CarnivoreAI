import type { Family, TypeRow } from './api';

export interface Group {
    readonly family: Family;
    readonly rows: readonly TypeRow[];
}

export function groupRows(families: readonly Family[], types: readonly TypeRow[]): Group[] {
    return families
        .map((family) => ({ family, rows: types.filter((row) => row.family === family.id && row.hidden !== true) }))
        .filter((group) => group.rows.length > 0);
}

export function linkReasonKey(reason: string): string {
    const known = ['mobile_sync_ready', 'mobile_sync_not_set_up', 'local_name_ready', 'lan_ip_ready', 'bound_loopback_only', 'bound_host_unknown', 'no_lan_address'];
    return `settings.notify.link.reason.${known.includes(reason) ? reason : 'unknown'}`;
}

export function linkKindKey(kind: string): string {
    return `settings.notify.link.kind.${['mobile_sync', 'local_name', 'lan_ip', 'none'].includes(kind) ? kind : 'none'}`;
}
