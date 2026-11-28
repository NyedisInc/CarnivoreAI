import type { authFetch } from '../../opscenter/api/auth.svelte';
import { authFetch as defaultFetch } from '../../opscenter/api/auth.svelte';
import { refreshEnablement } from '../../plugins/host/enablement.svelte';
import type { Translate } from '../sessions/types';
import { CPLUGS_ROUTE, dependencyRefusal, toCplugItem, type CplugItem, type CplugRow, type CplugSheet } from './cplugs-adapter';

export function readSheet(cplugId: string, fetcher: typeof authFetch = defaultFetch): Promise<CplugSheet> {
    return fetcher<CplugSheet>(`${CPLUGS_ROUTE}/${encodeURIComponent(cplugId)}/sheet`);
}

export function sheetStamp(sheet: CplugSheet): string {
    return sheet.ui_slots_sha !== undefined
        ? `${sheet.digest}|${sheet.body_sha}|${sheet.grants_sha}|${sheet.ui_slots_sha}`
        : `${sheet.digest}|${sheet.body_sha}|${sheet.grants_sha}`;
}

export interface GrantOptions {
    readonly enable?: boolean;
    readonly seen?: CplugSheet;
    readonly slotTicks?: readonly string[];
    readonly uiSlots?: readonly string[];
}

export async function grantCplug(
    cplugId: string,
    ticks: readonly string[],
    t: Translate,
    fetcher: typeof authFetch = defaultFetch,
    onChanged: () => Promise<void> = refreshEnablement,
    options: GrantOptions = {},
): Promise<CplugItem> {
    const path = `${CPLUGS_ROUTE}/${encodeURIComponent(cplugId)}`;
    const current = await fetcher<CplugRow>(path);
    const sheet = options.seen ?? (await fetcher<CplugSheet>(`${path}/sheet`));
    const sheetSlots = (sheet.ui_slots ?? []).map((s) => s.slot);
    const uiSlots = options.uiSlots ?? (sheetSlots.length > 0 ? sheetSlots : current.ui_contribute ? Object.keys(current.ui_contribute) : []);
    const includeSlots = uiSlots.length > 0 || (options.slotTicks?.length ?? 0) > 0 || sheet.ui_slots_sha !== undefined;
    const body = {
        revision: current.revision ?? 0,
        ...(options.enable ? { enabled: true } : {}),
        grants: {
            app: [...(current.permissions?.app ?? [])],
            ...(includeSlots && uiSlots.length > 0 ? { ui_slots: [...uiSlots] } : {}),
        },
        consent: {
            digest: sheet.digest,
            body_sha: sheet.body_sha,
            grants_sha: sheet.grants_sha,
            ticks: [...ticks],
            ...(includeSlots
                ? {
                      ...(sheet.ui_slots_sha !== undefined ? { ui_slots_sha: sheet.ui_slots_sha } : {}),
                      slot_ticks: [...(options.slotTicks ?? [])],
                  }
                : {}),
        },
    };
    let row: CplugRow;
    try {
        row = await fetcher<CplugRow>(path, { method: 'PUT', body: JSON.stringify(body) });
    } catch (error) {
        throw dependencyRefusal(error, t);
    }
    await onChanged();
    return toCplugItem(row, t);
}
