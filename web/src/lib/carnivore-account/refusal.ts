import { API_REFUSAL_EVENT } from '../../opscenter/api/auth.svelte';
import { ACCOUNT_FEATURES, type AccountFeature } from './features';
import { requireAccount } from './funnel';
import { openRegisterModal } from './open-register';

const REGISTRATION_CODES: ReadonlySet<string> = new Set([
    'handle_required', 'terms_required', 'age_required', 'registration_required',
]);

export type RefusalKind =
    | { kind: 'sign_in'; feature: AccountFeature | 'generic'; src: string }
    | { kind: 'register' }
    | null;

function field(body: unknown, key: string): string | null {
    if (!body || typeof body !== 'object') return null;
    const top = (body as Record<string, unknown>)[key];
    if (typeof top === 'string' && top) return top;
    const detail = (body as { detail?: unknown }).detail;
    const inner = detail && typeof detail === 'object' ? (detail as Record<string, unknown>)[key] : null;
    return typeof inner === 'string' && inner ? inner : null;
}

export function classifyRefusal(status: number, body: unknown): RefusalKind {
    if (status === 401) return null;
    const code = field(body, 'code');
    if (code === 'account_required') {
        const feature = field(body, 'feature');
        const known = (ACCOUNT_FEATURES as readonly string[]).includes(feature ?? '');
        return { kind: 'sign_in', feature: known ? (feature as AccountFeature) : 'generic', src: 'refusal' };
    }
    if (status === 403 && code === 'unauthorized') return { kind: 'sign_in', feature: 'generic', src: 'refusal' };
    if (code === 'session_revoked') return { kind: 'sign_in', feature: 'generic', src: 'revoked' };
    if (code && REGISTRATION_CODES.has(code)) return { kind: 'register' };
    return null;
}

let quietRegister = 0;

export async function withoutRegisterDialog<T>(work: () => Promise<T>): Promise<T> {
    quietRegister += 1;
    try {
        return await work();
    } finally {
        quietRegister -= 1;
    }
}

let signingIn = false;

function onRefusal(event: Event): void {
    const detail = (event as CustomEvent<{ status?: number; body?: unknown }>).detail;
    const verdict = classifyRefusal(Number(detail?.status), detail?.body);
    if (!verdict) return;
    if (verdict.kind === 'register') {
        if (quietRegister === 0) void openRegisterModal();
        return;
    }
    if (signingIn) return;
    signingIn = true;
    const done = (): void => { signingIn = false; };
    void requireAccount({
        feature: verdict.feature as AccountFeature,
        src: verdict.src,
        resume: done,
        cancelled: done,
    }).then((answer) => { if (answer === 'resumed') done(); }, done);
}

export function installRefusalHandler(): void {
    window.removeEventListener(API_REFUSAL_EVENT, onRefusal);
    window.addEventListener(API_REFUSAL_EVENT, onRefusal);
}
