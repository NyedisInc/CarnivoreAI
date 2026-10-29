import { sessionsHash } from '../sessions-page/sessions-route';
import { browserSessionsSearchHost } from '../sessions-search/host';
import { hostWindow } from '../sessions/env';

export interface ConversationTarget {
    conversationId: string;
    sessionUuid: string | null;
    projectId: number | null;
}

export type OpenOutcome = 'switched' | 'page' | 'none' | 'failed';

export interface LiveSession {
    sessionId: string;
    tmuxName: string;
}

export interface ConversationOpenHost {
    liveSessionFor(conversationId: string): Promise<LiveSession | null>;
    switchTo(session: LiveSession): Promise<boolean>;
    showHash(hash: string): void;
}

type Bag = Record<string, unknown>;
const isBag = (v: unknown): v is Bag => typeof v === 'object' && v !== null && !Array.isArray(v);

export function liveFromRows(rows: readonly unknown[], conversationId: string): LiveSession | null {
    for (const row of rows) {
        if (!isBag(row) || !isBag(row.session)) continue;
        const inner = row.session;
        if ((row.claude_session_uuid ?? inner.claude_session_uuid) !== conversationId || typeof inner.id !== 'string') continue;
        if (row.activity_status === 'dead') continue;
        const tmux = typeof row.tmux_session === 'string' ? row.tmux_session
            : typeof inner.tmux_session === 'string' ? inner.tmux_session : '';
        return { sessionId: inner.id, tmuxName: tmux };
    }
    return null;
}

export function browserConversationOpenHost(): ConversationOpenHost {
    const sessions = browserSessionsSearchHost();
    return {
        async liveSessionFor(conversationId) {
            const api = (hostWindow() as unknown as { API?: { listSessions?(): Promise<unknown[]> } } | undefined)?.API;
            if (!api?.listSessions) return null;
            try {
                return liveFromRows((await api.listSessions()) ?? [], conversationId);
            } catch (err) {
                console.warn('ConversationOpen: the session list could not be read', err);
                return null;
            }
        },
        switchTo: (session) => sessions.navigate(session.sessionId, session.tmuxName),
        showHash(hash) {
            const w = hostWindow();
            if (w) w.location.hash = hash;
        },
    };
}

export async function openConversation(target: ConversationTarget,
    host: ConversationOpenHost = browserConversationOpenHost()): Promise<OpenOutcome> {
    const live = await host.liveSessionFor(target.conversationId);
    if (live) {
        try {
            return (await host.switchTo(live)) ? 'switched' : 'failed';
        } catch (err) {
            console.warn('ConversationOpen: could not switch to the session', err);
            return 'failed';
        }
    }
    if (!target.sessionUuid) return 'none';
    host.showHash(sessionsHash({ session: target.sessionUuid }));
    return 'page';
}
