import { SCREEN, type Cell, type Column, type Family, type RoutingSettings, type TypeRow } from './api';

export const PHONE_QUERY = '(max-width: 1023px)';

export const DEFAULTS_COLUMN = 'defaults';

export interface Group {
    readonly family: Family;
    readonly rows: readonly TypeRow[];
}

export function groupRows(families: readonly Family[], types: readonly TypeRow[]): Group[] {
    return families
        .map((family) => ({ family, rows: types.filter((row) => row.family === family.id) }))
        .filter((group) => group.rows.length > 0);
}

export function destinationColumns(settings: RoutingSettings): Column[] {
    const named = new Set(settings.destinations.map((d) => d.id));
    const extra = Object.keys(settings.ticks)
        .filter((id) => !named.has(id))
        .map((id): Column => ({ id, name: '', kind: id.startsWith('webpush:') ? 'webpush' : '', enabled: true, scope: 'local' }));
    return [...settings.destinations, ...extra];
}

export function cellOf(settings: RoutingSettings, column: string, typeId: string): Cell | undefined {
    return column === SCREEN ? settings.screen[typeId] : settings.ticks[column]?.[typeId];
}

export function lockReason(row: TypeRow, column: string): '' | 'in_app' | 'health' {
    if (column === SCREEN) return '';
    if (!row.defaults.outside_locked_off) return '';
    return row.family === 'in_app' ? 'in_app' : 'health';
}

export function linkReasonKey(reason: string): string {
    const known = ['mobile_sync_ready', 'mobile_sync_not_set_up', 'local_name_ready', 'lan_ip_ready', 'bound_loopback_only', 'bound_host_unknown', 'no_lan_address'];
    return `settings.notify.link.reason.${known.includes(reason) ? reason : 'unknown'}`;
}

export function linkKindKey(kind: string): string {
    return `settings.notify.link.kind.${['mobile_sync', 'local_name', 'lan_ip', 'none'].includes(kind) ? kind : 'none'}`;
}
