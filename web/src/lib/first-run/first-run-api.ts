
import { detailReasonOf } from './detail-reason';

export type Entry = 'first-run' | 'remote' | 'totp' | 'joined';

export type Fetch = typeof fetch;

export const navigate = {
    reload(): void {
        location.reload();
    },
};

export const PROBE_TIMEOUT_MS = 3000;

export const HEALTH_TIMEOUT_MS = 2000;

export const MANUAL_AFTER_MS = 15_000;

export const FAST_POLL_MS = 60_000;

export const STOP_POLL_MS = 600_000;

async function timed(url: string, init: RequestInit, ms: number, fetcher: Fetch): Promise<Response> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), ms);
    try {
        return await fetcher(url, { ...init, signal: controller.signal });
    } finally {
        clearTimeout(timer);
    }
}

/* already running */
export async function decideEntry(fetcher: Fetch = fetch): Promise<Entry> {
    try {
        const reply = await timed('/api/v1/auth/enrollment/status', { credentials: 'same-origin', cache: 'no-store' }, PROBE_TIMEOUT_MS, fetcher);
        if (reply.status !== 200) return 'totp';
        const body = (await reply.json()) as { paired?: unknown; local?: unknown; joined?: unknown; join_pending?: unknown } | null;
        if (body && body.joined === true && body.local === true) return 'joined';
        if (body && body.join_pending === true && body.local === true) return 'first-run';
        if (!body || body.paired !== false) return 'totp';
        if (body.local === true) return 'first-run';
        if (body.local === false) return 'remote';
        return 'totp';
    } catch {
        return 'totp';
    }
}

export interface Enrollment {
    readonly qrImage: string;
    readonly secret: string;
}

export type EnrollmentFailure = 'remote' | 'already_paired' | 'joined' | 'restart_pending' | 'config' | 'load';

export type EnrollmentResult = { readonly ok: true; readonly enrollment: Enrollment } | { readonly ok: false; readonly failure: EnrollmentFailure };

export async function fetchEnrollment(fetcher: Fetch = fetch): Promise<EnrollmentResult> {
    let reply: Response;
    try {
        reply = await fetcher('/api/v1/auth/enrollment', { credentials: 'same-origin', cache: 'no-store' });
    } catch {
        return { ok: false, failure: 'load' };
    }
    const body: unknown = await reply.json().catch(() => null);
    if (reply.status === 403) return { ok: false, failure: 'remote' };
    const reason = detailReasonOf(body);
    if (reply.status === 409 && reason === 'joined') return { ok: false, failure: 'joined' };
    if (reply.status === 409 && reason === 'already_paired') return { ok: false, failure: 'already_paired' };
    if (reply.status === 409 && reason === 'restart_pending') return { ok: false, failure: 'restart_pending' };
    if (reply.status === 503 && (reason === 'config_unreadable' || reason === 'totp_not_configured')) return { ok: false, failure: 'config' };
    const data = body as { qr_image?: unknown; secret?: unknown } | null;
    if (reply.status !== 200 || !data || typeof data.qr_image !== 'string' || typeof data.secret !== 'string') return { ok: false, failure: 'load' };
    if (!data.qr_image.startsWith('data:image/svg+xml;base64,') || data.secret.length === 0) return { ok: false, failure: 'load' };
    return { ok: true, enrollment: { qrImage: data.qr_image, secret: data.secret } };
}

export type VerifyFailure = 'invalid' | 'reused' | 'rate_limited' | 'network';

export type VerifyResult = { readonly ok: true; readonly response: { access_token: string; refresh_token?: string } } | { readonly ok: false; readonly failure: VerifyFailure };

export async function verifyCode(code: string, fetcher: Fetch = fetch): Promise<VerifyResult> {
    let reply: Response;
    try {
        reply = await fetcher('/api/v1/auth/verify', {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'content-type': 'application/json' },
            body: JSON.stringify({ code }),
        });
    } catch {
        return { ok: false, failure: 'network' };
    }
    const body: unknown = await reply.json().catch(() => null);
    if (reply.status === 401) return { ok: false, failure: detailReasonOf(body) === 'code_reused' ? 'reused' : 'invalid' };
    if (reply.status === 429) return { ok: false, failure: 'rate_limited' };
    const data = body as { access_token?: unknown; token?: unknown; refresh_token?: unknown } | null;
    const access = typeof data?.access_token === 'string' ? data.access_token : typeof data?.token === 'string' ? data.token : '';
    if (!reply.ok || !access) return { ok: false, failure: 'network' };
    const refresh = typeof data?.refresh_token === 'string' ? data.refresh_token : undefined;
    return { ok: true, response: { access_token: access, ...(refresh ? { refresh_token: refresh } : {}) } };
}

export type HealthRead = { readonly ok: false } | { readonly ok: true; readonly restartRequired: boolean | null };

export async function readHealth(fetcher: Fetch = fetch): Promise<HealthRead> {
    try {
        const reply = await timed('/health', { credentials: 'same-origin', cache: 'no-store' }, HEALTH_TIMEOUT_MS, fetcher);
        if (reply.status !== 200) return { ok: false };
        const body = (await reply.json()) as { status?: unknown; bind?: unknown } | null;
        if (!body || body.status !== 'healthy') return { ok: false };
        const bind = body.bind;
        if (bind === null || typeof bind !== 'object' || Array.isArray(bind)) return { ok: false };
        const restart = (bind as { restart_required?: unknown }).restart_required;
        if (restart !== true && restart !== false && restart !== null) return { ok: false };
        return { ok: true, restartRequired: restart };
    } catch {
        return { ok: false };
    }
}

export interface WatchHooks {
    settled(sawDown: boolean): void;
    manual(): void;
}

export function watchRestart(initialSawDown: boolean, hooks: WatchHooks, read: () => Promise<HealthRead> = readHealth): () => void {
    const start = Date.now();
    let sawDown = initialSawDown;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const manualTimer = setTimeout(() => {
        if (!stopped) hooks.manual();
    }, MANUAL_AFTER_MS);

    const stop = (): void => {
        stopped = true;
        clearTimeout(timer);
        clearTimeout(manualTimer);
    };
    const tick = async (): Promise<void> => {
        const result = await read();
        if (stopped) return;
        if (!result.ok) sawDown = true;
        else if (result.restartRequired !== true) {
            stop();
            hooks.settled(sawDown);
            return;
        }
        const elapsed = Date.now() - start;
        if (elapsed >= STOP_POLL_MS) return;
        timer = setTimeout(() => void tick(), elapsed < FAST_POLL_MS ? 1000 : 5000);
    };
    timer = setTimeout(() => void tick(), 1000);
    return stop;
}
