import { ApiError, authFetch } from '../../../opscenter/api/auth.svelte';

export type Fetcher = typeof authFetch;

export interface DomainCheck {
    readonly result: string;
    readonly seen: string | null;
    readonly checked_at: number | null;
}

export interface DomainCert {
    readonly issuer: string;
    readonly not_after: string;
    readonly profile: string;
}

export interface CustomDomain {
    readonly domain: string | null;
    readonly domain_display: string | null;
    readonly state: 'none' | 'pending' | 'live' | 'dead' | 'lockout' | 'released';
    readonly target: string | null;
    readonly dead_reason: string | null;
    readonly lockout_until: number | null;
    readonly check: DomainCheck | null;
    readonly cert: DomainCert | null;
    readonly error: string | null;
    readonly updated_at: number;
}

const ROUTE = '/phone-link/custom-domain';

export const EMPTY: CustomDomain = {
    domain: null, domain_display: null, state: 'none', target: null, dead_reason: null,
    lockout_until: null, check: null, cert: null, error: null, updated_at: 0,
};

export async function getCustomDomain(fetcher: Fetcher = authFetch): Promise<CustomDomain> {
    const body = await fetcher<Partial<CustomDomain> | null>(ROUTE);
    return body && typeof body.state === 'string' ? { ...EMPTY, ...body } : EMPTY;
}

export const putCustomDomain = (domain: string, fetcher: Fetcher = authFetch) =>
    fetcher<CustomDomain>(ROUTE, { method: 'PUT', body: JSON.stringify({ domain }) });

export const deleteCustomDomain = (fetcher: Fetcher = authFetch) => fetcher<CustomDomain>(ROUTE, { method: 'DELETE' });

const CHECKS = ['wrong_target', 'flattened_or_proxied', 'no_cname', 'nxdomain', 'dns_error', 'resolver_disagree'];

export function checkMessage(view: CustomDomain): { key: string; params: Record<string, string> } | null {
    if (view.state !== 'pending' && view.state !== 'lockout' && view.state !== 'dead') return null;
    const check = view.check;
    if (!check || check.result === 'match' || !check.result) return null;
    const result = CHECKS.includes(check.result) ? check.result : 'dns_error';
    return { key: `phoneLink.customDomain.check.${result}`, params: { seen: check.seen ?? '' } };
}

export function stateKey(view: CustomDomain): string {
    if (view.state === 'dead' && view.dead_reason) return `phoneLink.customDomain.dead.${view.dead_reason}`;
    return `phoneLink.customDomain.state.${view.state}`;
}

export function ledOf(state: CustomDomain['state']): 'ok' | 'wait' | 'bad' | 'off' {
    if (state === 'live') return 'ok';
    if (state === 'pending' || state === 'lockout') return 'wait';
    if (state === 'dead') return 'bad';
    return 'off';
}

export function errorKey(code: string | null): string | null {
    if (!code) return null;
    const known = ['control_unreachable', 'certificate_failed', 'repair_failed'];
    if (known.includes(code)) return `phoneLink.customDomain.error.${code}`;
    return code.startsWith('control_refused') ? 'phoneLink.customDomain.error.control_refused' : 'phoneLink.customDomain.error.other';
}

export function refusalKey(error: unknown): string | null {
    if (!(error instanceof ApiError)) return null;
    const body = error.payload as { code?: string; reason?: string } | null;
    if (body?.code === 'bad_domain' && body.reason) return `phoneLink.customDomain.bad.${body.reason}`;
    const known = ['domain_exists', 'cd_limit', 'control_unreachable', 'acme_unreachable', 'no_domain'];
    return body?.code && known.includes(body.code) ? `phoneLink.customDomain.refused.${body.code}` : null;
}

export function agentPrompt(name: string, target: string, t: (key: string, params?: Record<string, string>) => string): string {
    return t('phoneLink.customDomain.agent_prompt', { name, target });
}
