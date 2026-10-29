import { detailReasonOf } from './detail-reason';
import type { Fetch } from './first-run-api';

export type JoinState = 'idle' | 'waiting_relay' | 'finding' | 'connecting' | 'linking' | 'joined' | 'failed';

export interface Candidate {
    readonly name: string;
    readonly fid: string;
    readonly fid_short: string;
    readonly label: string;
}

export const HELPER_LINE = 'bash -c "$(curl -fsSL --proto \'=https\' --tlsv1.2 https://carnivore.ai/install.sh)" _ --join';

export interface JoinStatus {
    readonly state: JoinState;
    readonly error: string | null;
    readonly main_label: string | null;
    readonly candidates: readonly Candidate[];
}

export type JoinErrorKey =
    | 'wrong_code_many' | 'used_up' | 'expired' | 'no_pack' | 'unreachable' | 'local_network_blocked'
    | 'main_mismatch' | 'helper_not_started' | 'incompatible' | 'busy' | 'rate_limited' | 'refused' | 'needs_owner' | 'bad_link';

const ERROR_KEYS: Readonly<Record<string, JoinErrorKey>> = {
    wrong_code: 'wrong_code_many',
    no_invite: 'used_up',
    expired: 'expired',
    no_pack: 'no_pack',
    unreachable: 'unreachable',
    local_network_blocked: 'local_network_blocked',
    main_mismatch: 'main_mismatch',
    helper_not_started: 'helper_not_started',
    no_relay: 'helper_not_started',
    incompatible: 'incompatible',
    busy: 'busy',
    rate_limited: 'rate_limited',
    refused: 'refused',
    needs_owner: 'needs_owner',
    bad_link: 'bad_link',
    join_has_peers: 'refused',
    join_failed: 'refused',
};

export function errorKeyFor(code: string | null): JoinErrorKey {
    return (code !== null && ERROR_KEYS[code]) || 'refused';
}

function parseStatus(body: unknown): JoinStatus | null {
    const doc = body as { state?: unknown; error?: unknown; main_label?: unknown; candidates?: unknown } | null;
    const states: readonly string[] = ['idle', 'waiting_relay', 'finding', 'connecting', 'linking', 'joined', 'failed'];
    if (!doc || typeof doc.state !== 'string' || !states.includes(doc.state)) return null;
    const candidates = Array.isArray(doc.candidates)
        ? doc.candidates
            .filter((c) => !!c && typeof c.name === 'string' && typeof c.fid === 'string' && typeof c.fid_short === 'string')
            .map((c): Candidate => ({ name: c.name, fid: c.fid, fid_short: c.fid_short, label: typeof c.label === 'string' && c.label !== '' ? c.label : `${c.name} ${c.fid_short}` }))
        : [];
    return {
        state: doc.state as JoinState,
        error: typeof doc.error === 'string' ? doc.error : null,
        main_label: typeof doc.main_label === 'string' ? doc.main_label : null,
        candidates,
    };
}

export async function fetchJoinStatus(fetcher: Fetch = fetch): Promise<JoinStatus | null> {
    try {
        const reply = await fetcher('/api/v1/auth/join/status', { credentials: 'same-origin', cache: 'no-store' });
        return reply.status === 200 ? parseStatus(await reply.json().catch(() => null)) : null;
    } catch {
        return null;
    }
}

export type StartResult = { readonly ok: true; readonly status: JoinStatus } | { readonly ok: false; readonly error: JoinErrorKey };

/* a network failure */
export async function startJoin(input: { code?: string; link?: string; candidateFid?: string }, fetcher: Fetch = fetch): Promise<StartResult> {
    const body: Record<string, string> = {};
    if (input.code !== undefined) body.code = input.code;
    if (input.link !== undefined) body.link = input.link;
    if (input.candidateFid !== undefined) body.candidate_fid = input.candidateFid;
    return postStart('/api/v1/auth/join', body, fetcher);
}

export async function startLook(fetcher: Fetch = fetch): Promise<StartResult> {
    return postStart('/api/v1/auth/join/look', {}, fetcher);
}

async function postStart(url: string, body: Record<string, string>, fetcher: Fetch): Promise<StartResult> {
    let reply: Response;
    try {
        reply = await fetcher(url, {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'content-type': 'application/json' },
            body: JSON.stringify(body),
        });
    } catch {
        return { ok: false, error: 'unreachable' };
    }
    const doc: unknown = await reply.json().catch(() => null);
    if (reply.status === 429) return { ok: false, error: 'rate_limited' };
    if (reply.status === 422) return { ok: false, error: detailReasonOf(doc) === 'bad_link' ? 'bad_link' : 'wrong_code_many' };
    const status = reply.ok ? parseStatus(doc) : null;
    return status ? { ok: true, status } : { ok: false, error: 'refused' };
}

export const JOIN_POLL_MS = 1000;

export function pollJoinStatus(onStatus: (status: JoinStatus) => boolean, read: () => Promise<JoinStatus | null> = fetchJoinStatus): () => void {
    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const tick = async (): Promise<void> => {
        const status = await read();
        if (stopped) return;
        if (status && onStatus(status)) return;
        timer = setTimeout(() => void tick(), JOIN_POLL_MS);
    };
    timer = setTimeout(() => void tick(), JOIN_POLL_MS);
    return () => {
        stopped = true;
        clearTimeout(timer);
    };
}

export interface DesktopBridge {
    localLogin?: () => Promise<{ access_token: string; refresh_token?: string } | null>;
}

export function desktopBridge(): DesktopBridge | null {
    const bridge = (window as unknown as { carnivoreDesktop?: DesktopBridge }).carnivoreDesktop;
    return bridge && typeof bridge.localLogin === 'function' ? bridge : null;
}
