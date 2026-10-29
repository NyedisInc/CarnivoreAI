import { ADMIN_KEYS } from '../../../client/js/labels/admin.js';
import { hasKey } from './text.js';

export const API_BASE = 'https://api.carnivore.ai/v1';

export interface Refusal {
    status: number;
    code: string;
    params: Record<string, unknown>;
}

export interface UserRow {
    user_id: string;
    provider?: string;
    login?: string;
    email?: string;
    seen_at?: number | null;
    disabled?: boolean;
    is_admin?: boolean;
    news_opt_in?: boolean;
}

export interface Me {
    user_id: string;
    login: string;
    provider: string;
    email?: string;
    handle?: string;
    is_admin: boolean;
}

export interface SubmissionRow {
    submission_id: string;
    status?: string;
    name?: string;
    handle?: string;
    version?: string;
    submitted_by_login?: string;
    created_at?: string;
    handle_status?: string;
    new_version?: boolean;
    prior_submitter_match?: boolean;
    kind?: string;
    file_count?: number;
    media_only?: boolean;
    item_id?: string;
    gate_state?: string;
    gate_outcome?: string;
    report_sha256?: string;
    overridable?: boolean;
    override?: { reason: string; by?: string; by_login?: string; at?: string };
    revocation_state?: string;
    revocation_reason?: string;
    revoked_at?: string;
}

export interface Submitter {
    handle: string;
    provider: string;
    email: string;
    account_age_days: number | null;
    prior_approvals: number | null;
}

export interface SubmissionFileEntry {
    path: string;
    size: number;
}

export interface SubmissionDetail extends SubmissionRow {
    submitter?: Submitter;
    files?: SubmissionFileEntry[];
}

export interface ReportFinding {
    code: string;
    detector: string;
    path?: string;
    line?: number;
}

export interface ReportGate {
    n: number;
    id: string;
    verdict: string;
    code: string;
    findings?: ReportFinding[];
}

export interface ReportReview {
    status?: string;
    verdict?: string;
    summary?: string;
    model?: string;
    reviewed_at?: string;
    warnings?: Array<{ kind: string; detail: string; file?: string; line?: number }>;
    coverage?: {
        text_files: number;
        total_chars: number;
        reviewed_chars: number;
        omitted_files: number;
        truncated_files: number;
        binary_files: number;
        complete: boolean;
    };
}

export interface ReportCodeInventory {
    file_count: number;
    total_bytes: number;
    files: Array<{ path: string; bytes: number }>;
    truncated: boolean;
}

export interface ReportDiff {
    first_release?: boolean;
    unavailable?: boolean;
    base_version?: string;
    added?: number;
    removed?: number;
    changed?: number;
    bytes_delta?: number;
    paths?: Array<{ path: string; change: string }>;
}

export interface GateReport {
    outcome?: string;
    app_sha?: string;
    grade?: string;
    gates?: ReportGate[];
    review?: ReportReview;
    code_inventory?: ReportCodeInventory;
    diff?: ReportDiff;
}

export interface ReportAnswer {
    submission_id: string;
    gate_state: string;
    report_sha256: string;
    overridable: boolean;
    report: GateReport;
}

export type SubmissionFile =
    | { kind: 'text'; text: string }
    | { kind: 'image'; size: number; type: string; data?: string };

export interface EmailFlow {
    session: string;
    destination: string;
}

export type Fetcher = (
    input: string,
    init?: {
        method?: string;
        headers?: Record<string, string>;
        body?: string;
    },
) => Promise<{
    ok: boolean;
    status: number;
    json(): Promise<unknown>;
    text?(): Promise<string>;
    headers?: { get(name: string): string | null };
}>;

export class ApiRefusal extends Error {
    readonly refusal: Refusal;

    constructor(refusal: Refusal) {
        super(refusal.code);
        this.name = 'ApiRefusal';
        this.refusal = refusal;
    }
}

export function refusalKey(code: string | null | undefined): string {
    const trimmed = String(code || '').trim();
    if (!trimmed) return ADMIN_KEYS.refusedUnrecognised;
    const own = 'admin.refused.' + trimmed;
    if (hasKey(own)) return own;
    const shared = 'skill.refused.' + trimmed;
    if (hasKey(shared)) return shared;
    return ADMIN_KEYS.refusedUnrecognised;
}

export function refusalMessage(
    refusal: Refusal | null | undefined,
    t: (key: string, params?: Record<string, unknown> | null) => string,
): string {
    if (!refusal) return '';
    const key = refusalKey(refusal.code);
    if (key === ADMIN_KEYS.refusedUnrecognised) {
        return t(key, { code: String(refusal.code || '').trim() });
    }
    return t(key, refusal.params);
}

export function whoText(me: Me): string {
    return me.handle || me.email || me.login || me.user_id;
}

export function mayChangeStanding(row: UserRow, me: Me | null): boolean {
    if (!me) return false;
    return row.user_id !== me.user_id;
}

/* when there is nothing to show */
export function seenAtText(seenAt: number | null | undefined): string {
    if (typeof seenAt !== 'number' || !Number.isFinite(seenAt) || seenAt <= 0) {
        return '';
    }
    const when = new Date(seenAt * 1000);
    const stamp = Number.isNaN(when.getTime()) ? '' : when.toISOString();
    return stamp.slice(0, 10);
}

export function standingAction(row: UserRow): 'enable' | 'disable' {
    return row.disabled === true ? 'enable' : 'disable';
}

export function adminAction(row: UserRow): 'grant' | 'revoke' {
    return row.is_admin === true ? 'revoke' : 'grant';
}

export const REASON_MAX_CHARS = 500;

export function reasonRefusal(reason: string, emptyCode = 'reject_needs_reason'): Refusal | null {
    const text = String(reason || '').trim();
    if (!text) return { status: 0, code: emptyCode, params: {} };
    if (text.length > REASON_MAX_CHARS) return { status: 0, code: 'reason_too_long', params: { max: REASON_MAX_CHARS } };
    return null;
}

export function isLegacyPending(row: SubmissionRow): boolean {
    return !row.gate_state && (!row.status || row.status === 'pending');
}

export function rejectionRefusal(reason: string): Refusal | null {
    if (String(reason || '').trim()) return null;
    return { status: 0, code: 'reject_needs_reason', params: {} };
}

export function disableRefusal(reason: string): Refusal | null {
    if (String(reason || '').trim()) return null;
    return { status: 0, code: 'reason_required', params: {} };
}

export function looksLikeCode(code: string): boolean {
    return /^[0-9]+$/.test(String(code || '').trim());
}

function toRefusal(status: number, body: unknown): Refusal {
    const record = (body && typeof body === 'object' ? body : {}) as Record<
        string,
        unknown
    >;
    const code = typeof record.code === 'string' ? record.code : '';
    const params: Record<string, unknown> = {};
    if (record.retry_after !== undefined) params.retry_after = record.retry_after;
    return { status, code, params };
}

export class AdminApi {
    private readonly fetcher: Fetcher;
    private readonly bearer: () => string;

    constructor(fetcher: Fetcher, bearer: () => string) {
        this.fetcher = fetcher;
        this.bearer = bearer;
    }

    async call(
        method: string,
        path: string,
        body: Record<string, unknown> | null,
        authed: boolean,
    ): Promise<unknown> {
        const headers: Record<string, string> = { accept: 'application/json' };
        if (body) headers['content-type'] = 'application/json';
        if (authed) {
            const token = this.bearer();
            if (token) headers.authorization = 'Bearer ' + token;
        }
        let answer;
        try {
            answer = await this.fetcher(API_BASE + path, {
                method,
                headers,
                ...(body ? { body: JSON.stringify(body) } : {}),
            });
        } catch (error) {
            throw new ApiRefusal({ status: 0, code: 'offline', params: {} });
        }
        let parsed: unknown = null;
        try {
            parsed = await answer.json();
        } catch (error) {
            parsed = null;
        }
        if (!answer.ok) throw new ApiRefusal(toRefusal(answer.status, parsed));
        return parsed;
    }

    async callText(path: string): Promise<string> {
        const headers: Record<string, string> = { accept: 'text/csv' };
        const token = this.bearer();
        if (token) headers.authorization = 'Bearer ' + token;
        let answer;
        try {
            answer = await this.fetcher(API_BASE + path, { method: 'GET', headers });
        } catch (error) {
            throw new ApiRefusal({ status: 0, code: 'offline', params: {} });
        }
        if (!answer.ok) {
            let parsed: unknown = null;
            try {
                parsed = await answer.json();
            } catch (error) {
                parsed = null;
            }
            throw new ApiRefusal(toRefusal(answer.status, parsed));
        }
        if (!answer.text) throw new ApiRefusal({ status: 0, code: 'offline', params: {} });
        return answer.text();
    }

    async submissionDetail(id: string): Promise<SubmissionDetail> {
        const body = await this.call(
            'GET',
            '/submissions/' + encodeURIComponent(id),
            null,
            true,
        );
        return (body && typeof body === 'object' ? body : {}) as SubmissionDetail;
    }

    async submissionFile(id: string, path: string): Promise<SubmissionFile> {
        const headers: Record<string, string> = {};
        const token = this.bearer();
        if (token) headers.authorization = 'Bearer ' + token;
        let answer;
        try {
            answer = await this.fetcher(
                API_BASE +
                    '/submissions/' + encodeURIComponent(id) +
                    '/file?path=' + encodeURIComponent(path),
                { method: 'GET', headers },
            );
        } catch (error) {
            throw new ApiRefusal({ status: 0, code: 'offline', params: {} });
        }
        const isJson = (answer.headers?.get('content-type') || '').includes('json');
        if (!answer.ok) {
            let parsed: unknown = null;
            try {
                parsed = isJson ? await answer.json() : null;
            } catch (error) {
                parsed = null;
            }
            throw new ApiRefusal(toRefusal(answer.status, parsed));
        }
        if (isJson) {
            const body = (await answer.json()) as Record<string, unknown>;
            return {
                kind: 'image',
                size: Number(body?.size) || 0,
                type: typeof body?.type === 'string' ? body.type : '',
                data: typeof body?.data_base64 === 'string' ? body.data_base64 : undefined,
            };
        }
        return { kind: 'text', text: answer.text ? await answer.text() : '' };
    }

    async start(email: string): Promise<EmailFlow> {
        const body = (await this.call(
            'POST',
            '/auth/email/start',
            { email },
            false,
        )) as Record<string, unknown>;
        return {
            session: typeof body?.session === 'string' ? body.session : '',
            destination:
                typeof body?.destination === 'string' ? body.destination : '',
        };
    }

    async verify(
        email: string,
        flow: EmailFlow,
        code: string,
    ): Promise<{ access_token: string; login: string; provider: string }> {
        const body: Record<string, unknown> = {
            email,
            session: flow.session,
            code,
        };
        const answer = (await this.call(
            'POST',
            '/auth/email/verify',
            body,
            false,
        )) as Record<string, unknown>;
        return {
            access_token:
                typeof answer?.access_token === 'string' ? answer.access_token : '',
            login: typeof answer?.login === 'string' ? answer.login : '',
            provider: typeof answer?.provider === 'string' ? answer.provider : '',
        };
    }

    async me(): Promise<Me> {
        const body = (await this.call('GET', '/me', null, true)) as Record<
            string,
            unknown
        >;
        return {
            user_id: typeof body?.user_id === 'string' ? body.user_id : '',
            login: typeof body?.login === 'string' ? body.login : '',
            provider: typeof body?.provider === 'string' ? body.provider : '',
            email: typeof body?.email === 'string' ? body.email : '',
            handle: typeof body?.handle === 'string' ? body.handle : '',
            is_admin: body?.is_admin === true,
        };
    }

    async users(cursor: string): Promise<{ users: UserRow[]; cursor: string }> {
        const path = cursor ? '/users?cursor=' + encodeURIComponent(cursor) : '/users';
        const body = (await this.call('GET', path, null, true)) as Record<
            string,
            unknown
        >;
        const rows = Array.isArray(body?.users) ? (body.users as UserRow[]) : [];
        return {
            users: rows,
            cursor: typeof body?.cursor === 'string' ? body.cursor : '',
        };
    }

    async setStanding(
        userId: string,
        action: 'disable' | 'enable',
        reason: string = '',
    ): Promise<unknown> {
        let body: Record<string, unknown> | null = null;
        if (action === 'disable') {
            const refusal = disableRefusal(reason);
            if (refusal) throw new ApiRefusal(refusal);
            body = { reason: reason.trim() };
        }
        return this.call(
            'POST',
            '/users/' + encodeURIComponent(userId) + '/' + action,
            body,
            true,
        );
    }

    async setAdmin(userId: string, admin: boolean): Promise<unknown> {
        return this.call(
            'POST',
            '/users/' + encodeURIComponent(userId) + '/admin',
            { admin },
            true,
        );
    }

    async submissions(status: string, gateState = ''): Promise<SubmissionRow[]> {
        const body = (await this.call(
            'GET',
            '/submissions?status=' + encodeURIComponent(status) +
                (gateState ? '&gate_state=' + encodeURIComponent(gateState) : ''),
            null,
            true,
        )) as Record<string, unknown>;
        return Array.isArray(body?.submissions)
            ? (body.submissions as SubmissionRow[])
            : [];
    }

    async report(submissionId: string): Promise<ReportAnswer> {
        const body = await this.call(
            'GET', '/admin/submissions/' + encodeURIComponent(submissionId) + '/report', null, true,
        );
        return (body && typeof body === 'object' ? body : {}) as ReportAnswer;
    }

    async approve(submissionId: string, reportSha256 = ''): Promise<unknown> {
        return this.call(
            'POST',
            '/submissions/' + encodeURIComponent(submissionId) + '/approve',
            reportSha256 ? { report_sha256: reportSha256 } : null,
            true,
        );
    }

    async override(submissionId: string, reason: string, reportSha256: string): Promise<unknown> {
        const refusal = reasonRefusal(reason);
        if (refusal) throw new ApiRefusal(refusal);
        return this.call(
            'POST',
            '/submissions/' + encodeURIComponent(submissionId) + '/override',
            { reason: reason.trim(), report_sha256: reportSha256 },
            true,
        );
    }

    async revoke(submissionId: string, reason: string): Promise<unknown> {
        const refusal = reasonRefusal(reason, 'revoke_needs_reason');
        if (refusal) throw new ApiRefusal(refusal);
        return this.call(
            'POST',
            '/admin/submissions/' + encodeURIComponent(submissionId) + '/revoke',
            { reason: reason.trim() },
            true,
        );
    }

    async regate(submissionId: string): Promise<unknown> {
        return this.call('POST', '/submissions/' + encodeURIComponent(submissionId) + '/regate', null, true);
    }

    async reject(submissionId: string, reason: string): Promise<unknown> {
        const refusal = reasonRefusal(reason);
        if (refusal) throw new ApiRefusal(refusal);
        return this.call(
            'POST',
            '/submissions/' + encodeURIComponent(submissionId) + '/reject',
            { reason: reason.trim() },
            true,
        );
    }
}
