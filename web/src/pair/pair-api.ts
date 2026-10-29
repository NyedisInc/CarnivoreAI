
export type Failure = 'link_used' | 'wrong_code' | 'wrong_otp' | 'pairing_dead' | 'bad_origin' | 'throttled' | 'unavailable' | 'network';

export type ClaimStatus = 'pending' | 'already_paired';

export type ClaimResult = { readonly ok: true; readonly status: ClaimStatus } | { readonly ok: false; readonly failure: Failure };

export type Fetch = typeof fetch;

function deviceLabel(): string {
    return /iPhone|iPad/.test(navigator.userAgent) ? 'iphone' : /Android/.test(navigator.userAgent) ? 'android' : 'phone';
}

async function post(path: string, body: Record<string, string>, wrong: Failure, fetcher: Fetch): Promise<ClaimResult> {
    let reply: Response;
    try {
        reply = await fetcher(path, {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'content-type': 'application/json' },
            body: JSON.stringify({ ...body, label: deviceLabel() }),
        });
    } catch {
        return { ok: false, failure: 'network' };
    }
    const answer = (await reply.json().catch(() => ({}))) as { status?: unknown; detail?: unknown };
    if (reply.status === 403) return { ok: false, failure: answer.detail === 'bad_origin' ? 'bad_origin' : wrong };
    if (reply.status === 429) return { ok: false, failure: 'throttled' };
    if (!reply.ok) return { ok: false, failure: 'unavailable' };
    const status: ClaimStatus = answer.status === 'already_paired' ? 'already_paired' : 'pending';
    return { ok: true, status };
}

export const claimSecret = (secret: string, fetcher: Fetch = fetch) => post('/pair/claim', { secret }, 'link_used', fetcher);

export const submitCode = (code: string, fetcher: Fetch = fetch) => post('/pair/code', { code: code.trim().toUpperCase() }, 'wrong_code', fetcher);

export type VerifyResult = { readonly ok: true; readonly accessToken: string; readonly refreshToken: string } | { readonly ok: false; readonly failure: Failure };

export async function verifyOtp(code: string, fetcher: Fetch = fetch): Promise<VerifyResult> {
    let reply: Response;
    try {
        reply = await fetcher('/pair/verify', {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'content-type': 'application/json' },
            body: JSON.stringify({ code: code.trim() }),
        });
    } catch {
        return { ok: false, failure: 'network' };
    }
    const answer = (await reply.json().catch(() => ({}))) as { detail?: unknown; access_token?: unknown; refresh_token?: unknown };
    if (reply.status === 401) return { ok: false, failure: 'wrong_otp' };
    if (reply.status === 403) return { ok: false, failure: answer.detail === 'bad_origin' ? 'bad_origin' : 'pairing_dead' };
    if (reply.status === 429) return { ok: false, failure: 'throttled' };
    if (!reply.ok || typeof answer.access_token !== 'string' || typeof answer.refresh_token !== 'string') return { ok: false, failure: 'unavailable' };
    return { ok: true, accessToken: answer.access_token, refreshToken: answer.refresh_token };
}

export function keepSession(accessToken: string, refreshToken: string): void {
    localStorage.setItem('claude_tunnel_token', accessToken);
    localStorage.setItem('claude_refresh_token', refreshToken);
}

export async function pairStatus(fetcher: Fetch = fetch): Promise<{ paired: boolean; pending: boolean }> {
    try {
        const reply = await fetcher('/pair/status', { credentials: 'same-origin' });
        const answer = reply.ok ? ((await reply.json()) as { paired?: unknown; pending?: unknown }) : {};
        return { paired: answer.paired === true, pending: answer.pending === true };
    } catch {
        return { paired: false, pending: false };
    }
}

export function isInstalledApp(): boolean {
    return window.matchMedia?.('(display-mode: standalone)').matches === true || (navigator as Navigator & { standalone?: boolean }).standalone === true;
}

export const navigate = {
    to(url: string): void {
        location.replace(url);
    },
};
