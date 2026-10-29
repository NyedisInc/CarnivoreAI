import { hostWindow } from '../sessions/env';
import { refusalCodeOf } from '../catalog/install-actions';

export interface CommentAuthor {
    handle?: string | null;
    publisher?: boolean | null;
}

export interface Comment {
    comment_id?: string | null;
    parent_id?: string | null;
    placeholder?: string | null;
    author?: CommentAuthor | null;
    body?: string | null;
    created_at?: number | null;
    edited?: boolean | null;
    edited_at?: number | null;
    status?: string | null;
    rating?: number | null;
    review_ref?: string | null;
    login?: string | null;
}

export interface Profile {
    handle?: string | null;
    joined?: string | null;
    bio?: string | null;
    links?: string[] | null;
    items?: string[] | null;
    publisher?: boolean | null;
}

export const REPORT_REASONS = [
    'spam',
    'abuse',
    'impersonation',
    'security',
    'copyright',
    'other',
] as const;
export type ReportReason = (typeof REPORT_REASONS)[number];

export type ReportTarget =
    | { kind: 'comment'; itemId: string; commentId: string }
    | { kind: 'review'; itemId: string; reviewRef: string };

export const MAX_COMMENT_CHARS = 2000;
export const EDIT_WINDOW_SECONDS = 15 * 60;

const GATE_CODES = new Set(['handle_required', 'terms_required', 'age_required', 'registration_required']);

export function isGateRefusal(error: unknown): boolean {
    const code = refusalCodeOf(error);
    return code !== null && GATE_CODES.has(code);
}

export interface CommunityHost {
    comments(itemId: string, cursor?: string): Promise<{ comments?: Comment[] | null; cursor?: string | null }>;
    myComments(itemId: string): Promise<{ comments?: Comment[] | null }>;
    post(itemId: string, body: { body: string; parent_id?: string }): Promise<{ comment?: Comment | null }>;
    edit(itemId: string, commentId: string, body: string): Promise<{ comment?: Comment | null }>;
    remove(itemId: string, commentId: string): Promise<unknown>;
    report(body: {
        kind: string;
        item_id: string;
        comment_id?: string;
        reviewer?: string;
        reason: string;
        note?: string;
    }): Promise<{ reported?: boolean | null }>;
    profile(handle: string): Promise<Profile>;
    setNotifyReplies(on: boolean): Promise<{ notify_replies?: boolean | null }>;
    readNotifyReplies(): Promise<boolean | null>;
}

interface LegacyApi {
    getCatalogComments: CommunityHost['comments'];
    getMyCatalogComments: CommunityHost['myComments'];
    postCatalogComment: CommunityHost['post'];
    editCatalogComment(itemId: string, commentId: string, body: { body: string }): ReturnType<CommunityHost['edit']>;
    deleteCatalogComment: CommunityHost['remove'];
    reportCatalog: CommunityHost['report'];
    getCatalogProfile: CommunityHost['profile'];
    setCatalogMailPreference(body: { notify_replies: boolean }): ReturnType<CommunityHost['setNotifyReplies']>;
    getPublishAccount(): Promise<{ notify_replies?: boolean | null }>;
}

export function browserCommunityHost(): CommunityHost {
    const api = (): LegacyApi =>
        (hostWindow() as unknown as { API: LegacyApi } | undefined)?.API as LegacyApi;
    return {
        comments: (itemId, cursor) => api().getCatalogComments(itemId, cursor),
        myComments: (itemId) => api().getMyCatalogComments(itemId),
        post: (itemId, body) => api().postCatalogComment(itemId, body),
        edit: (itemId, commentId, body) => api().editCatalogComment(itemId, commentId, { body }),
        remove: (itemId, commentId) => api().deleteCatalogComment(itemId, commentId),
        report: (body) => api().reportCatalog(body),
        profile: (handle) => api().getCatalogProfile(handle),
        setNotifyReplies: (on) => api().setCatalogMailPreference({ notify_replies: on }),
        readNotifyReplies: async () => {
            const account = await api().getPublishAccount();
            return typeof account?.notify_replies === 'boolean' ? account.notify_replies : null;
        },
    };
}

export interface ThreadNode {
    comment: Comment;
    mine: boolean;
    held: boolean;
    replies: ThreadNode[];
}

const HIDDEN = new Set(['hidden', 'removed', 'deleted']);

export function buildThread(pub: readonly Comment[], mine: readonly Comment[]): ThreadNode[] {
    const mineById = new Map<string, Comment>();
    for (const c of mine) if (c.comment_id) mineById.set(c.comment_id, c);
    const seen = new Set<string>();
    const nodes: ThreadNode[] = [];
    const push = (c: Comment): void => {
        const id = c.comment_id;
        if (!id || seen.has(id)) return;
        const own = mineById.get(id);
        const status = (own ?? c).status ?? null;
        if (status === 'held' && !own) return;
        if (status !== null && HIDDEN.has(status) && !c.placeholder) return;
        seen.add(id);
        nodes.push({ comment: own && status === 'held' ? own : c, mine: own !== undefined, held: status === 'held', replies: [] });
    };
    for (const c of pub) push(c);
    for (const c of mine) if (c.status === 'held') push(c);
    const byId = new Map(nodes.map((n) => [n.comment.comment_id as string, n]));
    const top: ThreadNode[] = [];
    for (const node of nodes) {
        let parent = node.comment.parent_id ? byId.get(node.comment.parent_id) : undefined;
        while (parent && parent.comment.parent_id && byId.has(parent.comment.parent_id)) {
            parent = byId.get(parent.comment.parent_id);
        }
        if (parent && parent !== node) parent.replies.push(node);
        else top.push(node);
    }
    const order = (a: ThreadNode, b: ThreadNode): number =>
        (a.comment.created_at ?? 0) - (b.comment.created_at ?? 0);
    top.sort(order);
    for (const n of top) n.replies.sort(order);
    return top;
}

export function canEdit(comment: Comment, nowSeconds: number): boolean {
    const at = comment.created_at;
    return typeof at === 'number' && nowSeconds - at <= EDIT_WINDOW_SECONDS;
}

export function dayOf(seconds: number | null | undefined): string {
    if (typeof seconds !== 'number' || !Number.isFinite(seconds)) return '';
    return new Date(seconds * 1000).toISOString().slice(0, 10);
}
