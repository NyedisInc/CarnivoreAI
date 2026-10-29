import { AdminApi, type Refusal } from './admin.js';
import { refusalOf } from './refusal-of';
import {
    auditDay, commentAct, commentQueue, itemComments, dismissReports, openReports, readMode, reviewAct, reviewsOf, userActivity, writeMode,
    type Activity, type AuditEntry, type CommentAction, type CommentMode, type QueueComment,
    type ReportGroup, type ReviewAction, type ReviewRow,
} from './moderation.js';

export interface CommunityHost {
    readonly refusal: Refusal | null;
    readonly busy: boolean;
    readonly loaded: boolean;
    readonly comments: QueueComment[];
    readonly mode: CommentMode;
    readonly pendingMode: CommentMode | null;
    readonly reason: string;
    readonly commentItem: string;
    readonly itemRows: QueueComment[];
    readonly itemRowsLoaded: boolean;
    readonly reviewItem: string;
    readonly reviews: ReviewRow[];
    readonly reviewsLoaded: boolean;
    readonly reports: ReportGroup[];
    readonly reportsLoaded: boolean;
    readonly day: string;
    readonly entries: AuditEntry[];
    readonly auditLoaded: boolean;
    readonly auditMore: boolean;
    readonly activity: Activity | null;
    load(): Promise<void>;
    setReason(value: string): void;
    comment(action: CommentAction, row: QueueComment): Promise<void>;
    askMode(mode: CommentMode): void;
    cancelMode(): void;
    confirmMode(): Promise<void>;
    setCommentItem(value: string): void;
    loadItemComments(): Promise<void>;
    setReviewItem(value: string): void;
    loadReviews(): Promise<void>;
    review(action: ReviewAction, row: ReviewRow): Promise<void>;
    loadReports(): Promise<void>;
    dismissReport(group: ReportGroup): Promise<void>;
    openReviews(itemId: string): Promise<void>;
    setDay(value: string): void;
    loadAudit(): Promise<void>;
    loadMoreAudit(): Promise<void>;
    loadActivity(userId: string): Promise<void>;
    closeActivity(): void;
    reset(): void;
}

function today(): string {
    return new Date().toISOString().slice(0, 10);
}

export function createCommunityHost(deps: {
    api: AdminApi;
    onUnauthorized?: () => void;
}): CommunityHost {
    const { api, onUnauthorized } = deps;

    let refusal = $state<Refusal | null>(null);
    let busy = $state(false);
    let loaded = $state(false);
    let comments = $state<QueueComment[]>([]);
    let mode = $state<CommentMode>('instant');
    let pendingMode = $state<CommentMode | null>(null);
    let reason = $state('');
    let commentItem = $state('');
    let itemRows = $state<QueueComment[]>([]);
    let itemRowsLoaded = $state(false);
    let reviewItem = $state('');
    let reviews = $state<ReviewRow[]>([]);
    let reviewsLoaded = $state(false);
    let reports = $state<ReportGroup[]>([]);
    let reportsLoaded = $state(false);
    let day = $state(today());
    let entries = $state<AuditEntry[]>([]);
    let auditLoaded = $state(false);
    let auditNext = $state('');
    let activity = $state<Activity | null>(null);

    /* a 401 signs out */
    async function guard(work: () => Promise<void>): Promise<boolean> {
        busy = true;
        refusal = null;
        try {
            await work();
            return true;
        } catch (error) {
            const shaped = refusalOf(error);
            if (shaped.status === 401) onUnauthorized?.();
            refusal = shaped;
            return false;
        } finally {
            busy = false;
        }
    }

    async function load(): Promise<void> {
        await guard(async () => {
            comments = await commentQueue(api);
            mode = await readMode(api);
            loaded = true;
        });
    }

    async function loadItemComments(): Promise<void> {
        const item = commentItem.trim();
        if (!item) return;
        await guard(async () => {
            itemRows = await itemComments(api, item);
            itemRowsLoaded = true;
        });
    }

    async function loadReviews(): Promise<void> {
        const item = reviewItem.trim();
        if (!item) return;
        await guard(async () => {
            reviews = await reviewsOf(api, item);
            reviewsLoaded = true;
        });
    }

    async function loadReports(): Promise<void> {
        await guard(async () => {
            reports = await openReports(api);
            reportsLoaded = true;
        });
    }

    return {
        get refusal() { return refusal; },
        get busy() { return busy; },
        get loaded() { return loaded; },
        get comments() { return comments; },
        get mode() { return mode; },
        get pendingMode() { return pendingMode; },
        get reason() { return reason; },
        get commentItem() { return commentItem; },
        get itemRows() { return itemRows; },
        get itemRowsLoaded() { return itemRowsLoaded; },
        get reviewItem() { return reviewItem; },
        get reviews() { return reviews; },
        get reviewsLoaded() { return reviewsLoaded; },
        get reports() { return reports; },
        get reportsLoaded() { return reportsLoaded; },
        get day() { return day; },
        get entries() { return entries; },
        get auditLoaded() { return auditLoaded; },
        get auditMore() { return auditNext !== ''; },
        get activity() { return activity; },

        load,

        setReason(value: string): void { reason = value; },

        async comment(action: CommentAction, row: QueueComment): Promise<void> {
            const sent = reason;
            const ok = await guard(async () => {
                await commentAct(api, action, row.item_id, row.comment_id, sent);
            });
            if (ok) {
                reason = '';
                await load();
                if (itemRowsLoaded) await loadItemComments();
            }
        },

        askMode(wanted: CommentMode): void {
            if (wanted !== mode) pendingMode = wanted;
        },

        cancelMode(): void { pendingMode = null; },

        async confirmMode(): Promise<void> {
            const wanted = pendingMode;
            if (!wanted) return;
            const ok = await guard(async () => {
                mode = await writeMode(api, wanted);
            });
            if (ok) pendingMode = null;
        },

        setCommentItem(value: string): void { commentItem = value; },

        loadItemComments,

        setReviewItem(value: string): void { reviewItem = value; },

        loadReviews,

        async review(action: ReviewAction, row: ReviewRow): Promise<void> {
            const sent = reason;
            const item = reviewItem.trim();
            const ok = await guard(async () => {
                await reviewAct(api, action, item, row.review_ref, sent);
            });
            if (ok) {
                reason = '';
                await loadReviews();
            }
        },

        loadReports,

        async dismissReport(group: ReportGroup): Promise<void> {
            const sent = reason;
            const ok = await guard(async () => {
                await dismissReports(api, group, sent);
            });
            if (ok) {
                reason = '';
                await loadReports();
            }
        },

        async openReviews(itemId: string): Promise<void> {
            reviewItem = itemId;
            await loadReviews();
        },

        setDay(value: string): void { day = value; },

        async loadAudit(): Promise<void> {
            await guard(async () => {
                const page = await auditDay(api, day.trim(), '');
                entries = page.entries;
                auditNext = page.next;
                auditLoaded = true;
            });
        },

        async loadMoreAudit(): Promise<void> {
            if (!auditNext) return;
            await guard(async () => {
                const page = await auditDay(api, day.trim(), auditNext);
                entries = [...entries, ...page.entries];
                auditNext = page.next;
            });
        },

        async loadActivity(userId: string): Promise<void> {
            await guard(async () => {
                activity = await userActivity(api, userId);
            });
        },

        closeActivity(): void { activity = null; },

        reset(): void {
            refusal = null;
            loaded = false;
            comments = [];
            mode = 'instant';
            pendingMode = null;
            reason = '';
            commentItem = '';
            itemRows = [];
            itemRowsLoaded = false;
            reviewItem = '';
            reviews = [];
            reviewsLoaded = false;
            reports = [];
            reportsLoaded = false;
            day = today();
            entries = [];
            auditLoaded = false;
            auditNext = '';
            activity = null;
        },
    };
}
