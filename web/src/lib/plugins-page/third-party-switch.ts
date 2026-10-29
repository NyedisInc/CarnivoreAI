import { authFetch } from '../../opscenter/api/auth.svelte';

export interface ThirdPartyStatus {
    enabled: boolean;
    safe_mode: { env: boolean; owner: boolean; active: boolean };
    sandbox: { ok: boolean; detail: string } | null;
}

const ROUTE = '/cplug-owner/switch';

export function loadThirdParty(fetcher: typeof authFetch = authFetch): Promise<ThirdPartyStatus> {
    return fetcher<ThirdPartyStatus>(ROUTE);
}

export function saveThirdParty(enabled: boolean, fetcher: typeof authFetch = authFetch): Promise<ThirdPartyStatus> {
    return fetcher<ThirdPartyStatus>(ROUTE, { method: 'PUT', body: JSON.stringify({ enabled }) });
}

export function sandboxLine(status: ThirdPartyStatus): { key: string; reason?: string } {
    if (!status.sandbox) return { key: 'plugins.page.third_party.sandbox.unchecked' };
    return status.sandbox.ok ? { key: 'plugins.page.third_party.sandbox.ok' } : { key: 'plugins.page.third_party.sandbox.bad', reason: status.sandbox.detail };
}
