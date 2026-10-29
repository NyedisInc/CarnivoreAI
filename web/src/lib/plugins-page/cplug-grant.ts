import type { authFetch } from '../../opscenter/api/auth.svelte';
import { authFetch as defaultFetch } from '../../opscenter/api/auth.svelte';
import { refreshEnablement } from '../../cplugs/host/enablement.svelte';
import type { Translate } from '../sessions/types';
import { CPLUGS_ROUTE, dependencyRefusal, toCplugItem, type CplugItem, type CplugRow, type CplugSheet } from './cplugs-adapter';

export function readSheet(cplugId: string, fetcher: typeof authFetch = defaultFetch): Promise<CplugSheet> {
    return fetcher<CplugSheet>(`${CPLUGS_ROUTE}/${encodeURIComponent(cplugId)}/sheet`);
}

export function sheetStamp(sheet: CplugSheet): string {
    return `${sheet.digest}|${sheet.body_sha}|${sheet.grants_sha}`;
}

export interface GrantOptions {
    readonly enable?: boolean;
    readonly seen?: CplugSheet;
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
    const body = {
        revision: current.revision ?? 0,
        ...(options.enable ? { enabled: true } : {}),
        grants: { app: [...(current.permissions?.app ?? [])] },
        consent: { digest: sheet.digest, body_sha: sheet.body_sha, grants_sha: sheet.grants_sha, ticks: [...ticks] },
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
