import { authFetch } from '../../opscenter/api/auth.svelte';
import { bookmarksTopic, type BookmarkList } from '../bookmarks/api';
import { resourcePush } from '../resource-push/boot';
import { SESSION_TIMELINE_TOPIC } from '../../opscenter/api/session-timeline.svelte';
import type { SessionTimeline } from '../../opscenter/cells/timeline/types';

const POLL_MS = 15000;

const TIMELINE_POLL_MS = 30000;

export interface PanelConversation {
    readonly conversation_id: string;
    readonly current: boolean;
    readonly started_at: string | null;
    readonly ended_at: string | null;
    readonly ended_reason: string | null;
    readonly first_prompt: string;
    readonly summary: string | null;
    readonly transcript_on_disk: boolean;
}

export interface PanelConversations {
    readonly current: PanelConversation | null;
    readonly previous: readonly PanelConversation[];
}

export interface PanelReaders {
    conversations(sessionUuid: string): Promise<PanelConversations>;
    bookmarks(sessionUuid: string): Promise<BookmarkList>;
    timeline(sessionUuid: string): Promise<SessionTimeline>;
    resume(sessionUuid: string, conversationId: string): Promise<void>;
}

const seg = (value: string): string => encodeURIComponent(value);

export const defaultPanelReaders: PanelReaders = {
    conversations: (uuid) => authFetch<PanelConversations>(`/sessions/${seg(uuid)}/conversations`),
    bookmarks: (uuid) => authFetch<BookmarkList>(`/sessions/${seg(uuid)}/bookmarks`),
    timeline: (uuid) => authFetch<SessionTimeline>(`/sessions/${seg(uuid)}/timeline`),
    resume: async (uuid, id) => {
        await authFetch(`/sessions/${seg(uuid)}/conversations/${seg(id)}/resume`, { method: 'POST' });
    },
};

export function conversationsOf(list: PanelConversations | null): readonly PanelConversation[] {
    if (!list) return [];
    return list.current ? [list.current, ...list.previous] : [...list.previous];
}

export interface ConversationTimeline {
    readonly busySeconds: number | null;
    readonly compacts: readonly { readonly id: string; readonly at: string | null }[];
}

export function timelineOf(timeline: SessionTimeline | null, conversationId: string): ConversationTimeline {
    const measured = (timeline?.bars ?? []).filter((bar) => bar.conversation_id === conversationId && typeof bar.busy_seconds === 'number');
    const busySeconds = measured.length ? measured.reduce((sum, bar) => sum + (bar.busy_seconds ?? 0), 0) : null;
    const compacts = (timeline?.marks ?? []).filter((m) => m.conversation_id === conversationId && m.kind === 'compact').map((m) => ({ id: m.id, at: m.at }));
    return { busySeconds, compacts };
}

export class PanelData {
    conversations = $state<PanelConversations | null>(null);
    convStatus = $state<'idle' | 'loading' | 'ready' | 'error'>('idle');
    bookmarks = $state<BookmarkList | null>(null);
    marksStatus = $state<'idle' | 'loading' | 'ready' | 'error'>('idle');
    timeline = $state<SessionTimeline | null>(null);
    /* conversation id */
    resuming = $state<string | null>(null);

    readonly #readers: PanelReaders;
    #uuid: string | null = null;
    #ticket = 0;
    #stop: (() => void) | null = null;
    #stopTimeline: (() => void) | null = null;

    constructor(readers: PanelReaders = defaultPanelReaders) {
        this.#readers = readers;
    }

    follow(sessionUuid: string, claude: boolean, rowId: number | null): void {
        this.stop();
        this.#uuid = sessionUuid;
        this.conversations = null;
        this.bookmarks = null;
        this.timeline = null;
        this.convStatus = 'loading';
        this.marksStatus = claude ? 'loading' : 'idle';
        void this.readConversations();
        void this.readTimeline();
        if (rowId !== null) this.#stopTimeline = resourcePush().pushOrPoll(() => void this.readTimeline(), TIMELINE_POLL_MS, [SESSION_TIMELINE_TOPIC, bookmarksTopic(rowId)]);
        if (!claude) return;
        void this.readMarks();
        if (rowId !== null) this.#stop = resourcePush().pushOrPoll(() => void this.readMarks(), POLL_MS, [bookmarksTopic(rowId)]);
    }

    stop(): void {
        this.#ticket += 1;
        this.#stop?.();
        this.#stop = null;
        this.#stopTimeline?.();
        this.#stopTimeline = null;
        this.#uuid = null;
    }

    async readConversations(): Promise<void> {
        const uuid = this.#uuid;
        if (!uuid) return;
        const mine = this.#ticket;
        try {
            const list = await this.#readers.conversations(uuid);
            if (mine !== this.#ticket) return;
            this.conversations = list;
            this.convStatus = 'ready';
        } catch (error) {
            if (mine !== this.#ticket) return;
            console.warn('CloudeOpscenter: conversations unavailable for the sessions panel', error);
            this.convStatus = 'error';
        }
    }

    async readTimeline(): Promise<void> {
        const uuid = this.#uuid;
        if (!uuid) return;
        const mine = this.#ticket;
        try {
            const tl = await this.#readers.timeline(uuid);
            if (mine === this.#ticket) this.timeline = tl;
        } catch (error) {
            if (mine === this.#ticket) console.warn('CloudeOpscenter: timeline unavailable for the sessions panel', error);
        }
    }

    async readMarks(): Promise<void> {
        const uuid = this.#uuid;
        if (!uuid) return;
        const mine = this.#ticket;
        try {
            const list = await this.#readers.bookmarks(uuid);
            if (mine !== this.#ticket) return;
            this.bookmarks = list;
            this.marksStatus = 'ready';
        } catch (error) {
            if (mine !== this.#ticket) return;
            console.warn('CloudeOpscenter: bookmarks unavailable for the sessions panel', error);
            this.marksStatus = 'error';
        }
    }

    async resume(conversationId: string): Promise<void> {
        const uuid = this.#uuid;
        if (!uuid || this.resuming) return;
        this.resuming = conversationId;
        try {
            await this.#readers.resume(uuid, conversationId);
        } finally {
            this.resuming = null;
        }
    }
}
