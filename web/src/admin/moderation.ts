import { AdminApi, ApiRefusal, disableRefusal } from './admin.js';

export type CommentMode = 'instant' | 'hold_all';

export type CommentAction = 'hide' | 'restore' | 'delete' | 'dismiss';

export type ReviewAction = 'hide' | 'restore' | 'remove';

export interface QueueComment {
    item_id: string;
    comment_id: string;
    status: string;
    queue?: string | null;
    body: string;
    created_at: number;
    author_id?: string | null;
    author_handle?: string | null;
    reasons?: Record<string, number>;
}

export interface ReportGroup {
    kind: string;
    item_id: string;
    ref: string;
    count: number;
    reasons: Record<string, number>;
    first_at: number;
    last_at: number;
    reporters: string[];
}

export interface ReviewRow {
    review_ref: string;
    author?: string | null;
    login?: string;
    stars: number;
    text: string;
    updated_at: number;
    status?: string;
}

export interface AuditEntry {
    audit_id?: string;
    at?: number;
    actor_id?: string;
    actor_handle?: string | null;
    actor_deleted?: boolean;
    target_handle?: string | null;
    target_deleted?: boolean;
    action?: string;
    target?: unknown;
    detail?: unknown;
}

export interface Activity {
    user_id: string;
    handle: string;
    disabled: boolean;
    comments: Array<{ item_id: string; comment_id: string; status: string; body: string; created_at: number }>;
    reviews: Array<{ review_ref?: string; stars?: number; text?: string }> | null;
    submissions: Array<{ submission_id?: string; name?: string; status?: string }>;
    sessions_count: number;
    reports: unknown;
}

function listOf<T>(body: unknown, key: string): T[] {
    const value = (body as Record<string, unknown> | null)?.[key];
    return Array.isArray(value) ? (value as T[]) : [];
}

export async function commentQueue(api: AdminApi): Promise<QueueComment[]> {
    return listOf<QueueComment>(await api.call('GET', '/moderation/queue', null, true), 'comments');
}

export async function itemComments(api: AdminApi, itemId: string): Promise<QueueComment[]> {
    const path = '/moderation/comments?item_id=' + encodeURIComponent(itemId);
    return listOf<QueueComment>(await api.call('GET', path, null, true), 'comments');
}

function requireReason(reason: string): void {
    const refusal = disableRefusal(reason);
    if (refusal) throw new ApiRefusal(refusal);
}

export async function commentAct(
    api: AdminApi, action: CommentAction, itemId: string, commentId: string, reason: string,
): Promise<unknown> {
    if (action === 'hide' || action === 'delete') requireReason(reason);
    return api.call(
        'POST', '/moderation/' + action,
        { item_id: itemId, comment_id: commentId, reason: reason.trim() }, true,
    );
}

export async function openReports(api: AdminApi): Promise<ReportGroup[]> {
    const groups: ReportGroup[] = [];
    for (const kind of ['item', 'review']) {
        const body = await api.call('GET', '/moderation/reports?kind=' + kind, null, true);
        groups.push(...listOf<ReportGroup>(body, 'groups'));
    }
    return groups.sort((a, b) => a.first_at - b.first_at);
}

export async function dismissReports(api: AdminApi, group: ReportGroup, reason: string): Promise<unknown> {
    const body: Record<string, string> = { kind: group.kind, item_id: group.item_id, reason: reason.trim() };
    if (group.kind === 'review') body.reviewer = group.ref;
    return api.call('POST', '/moderation/reports/dismiss', body, true);
}

export async function readMode(api: AdminApi): Promise<CommentMode> {
    const body = (await api.call('GET', '/moderation/mode', null, true)) as Record<string, unknown>;
    return body?.mode === 'hold_all' ? 'hold_all' : 'instant';
}

export async function writeMode(api: AdminApi, mode: CommentMode): Promise<CommentMode> {
    const body = (await api.call('PUT', '/moderation/mode', { mode }, true)) as Record<string, unknown>;
    return body?.mode === 'hold_all' ? 'hold_all' : 'instant';
}

/*  hidden  */
export async function reviewsOf(api: AdminApi, itemId: string): Promise<ReviewRow[]> {
    const path = '/moderation/reviews?item_id=' + encodeURIComponent(itemId);
    return listOf<ReviewRow>(await api.call('GET', path, null, true), 'reviews');
}

export async function reviewAct(
    api: AdminApi, action: ReviewAction, itemId: string, reviewRef: string, reason: string,
): Promise<unknown> {
    if (action === 'hide' || action === 'remove') requireReason(reason);
    return api.call(
        'POST', '/moderation/reviews/' + action,
        { item_id: itemId, review_ref: reviewRef, reason: reason.trim() }, true,
    );
}

export interface AuditPage {
    entries: AuditEntry[];
    next: string;
}

export async function auditDay(api: AdminApi, day: string, after: string): Promise<AuditPage> {
    let path = '/moderation/audit?day=' + encodeURIComponent(day);
    if (after) path += '&after=' + encodeURIComponent(after);
    const body = await api.call('GET', path, null, true);
    const next = (body as Record<string, unknown> | null)?.next;
    return { entries: listOf<AuditEntry>(body, 'entries'), next: typeof next === 'string' ? next : '' };
}

export async function userActivity(api: AdminApi, userId: string): Promise<Activity> {
    const body = (await api.call(
        'GET', '/users/' + encodeURIComponent(userId) + '/activity', null, true,
    )) as Record<string, unknown>;
    return {
        user_id: String(body?.user_id || ''),
        handle: String(body?.handle || ''),
        disabled: body?.disabled === true,
        comments: listOf(body, 'comments'),
        reviews: Array.isArray(body?.reviews) ? (body.reviews as Activity['reviews']) : null,
        submissions: listOf(body, 'submissions'),
        sessions_count: Number(body?.sessions_count || 0),
        reports: body?.reports ?? null,
    };
}

export function auditTime(at: number | undefined): string {
    if (typeof at !== 'number' || !Number.isFinite(at) || at <= 0) return '';
    return new Date(at * 1000).toISOString().slice(0, 16).replace('T', ' ');
}

export function auditActor(row: AuditEntry): string {
    if (row.actor_handle) return row.actor_handle;
    if (row.actor_deleted) return 'deleted account';
    return row.actor_id || '';
}

export function auditTarget(row: AuditEntry): string {
    const t = row.target;
    if (!t || typeof t !== 'object') return '';
    const v = t as Record<string, unknown>;
    const s = (key: string): string => (v[key] === undefined ? '' : String(v[key]));
    if (s('path') && s('submission_id')) return `file ${s('path')} of submission ${s('submission_id')}`;
    if (s('submission_id')) return `submission ${s('submission_id')}`;
    if (s('comment_id')) return `comment on ${s('item_id')}`;
    if (s('review_ref')) return `review ${s('review_ref')} on ${s('item_id')}`;
    if (s('user_id')) return 'account ' + (row.target_handle || (row.target_deleted ? 'deleted account' : s('user_id')));
    if (s('kind') && s('item_id')) return `${s('kind')} reports on ${s('item_id')}` + (s('ref') ? ` ref ${s('ref')}` : '');
    if (s('mode')) return `comment mode ${s('mode')}`;
    return Object.keys(v).sort().map((key) => `${key} ${s(key)}`).join(' ');
}

export function auditReason(detail: unknown): string {
    const reason = (detail as { reason?: unknown } | null)?.reason;
    return typeof reason === 'string' ? reason : '';
}
