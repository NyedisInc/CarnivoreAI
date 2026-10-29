import { ApiError } from '../../opscenter/api/auth.svelte';
import { resourcePush } from '../resource-push/boot';
import { errorText } from '../settings-page/panel-kit/error-text';
import { fetchBindings, fetchConversations, fetchMessages, fetchProviders, type Binding, type Conversation, type Fetcher, type Message, type Provider } from './api';

export const TOPIC = 'messaging';

export const FALLBACK_MS = 15000;

export const LOG_LIMIT = 50;

export const messaging = $state<{
    providers: Provider[];
    conversations: Conversation[];
    bindings: Binding[];
    messages: Message[];
    loaded: boolean;
    problem: string;
}>({ providers: [], conversations: [], bindings: [], messages: [], loaded: false, problem: '' });

let fetcherInUse: Fetcher | undefined;
let inflight: Promise<void> | null = null;
let attached = 0;
let stop: (() => void) | null = null;

export function refusalCode(error: unknown): string | null {
    if (!(error instanceof ApiError)) return null;
    const detail = (error.payload as { detail?: unknown } | null)?.detail;
    const code = detail && typeof detail === 'object' ? (detail as { code?: unknown }).code : null;
    return typeof code === 'string' ? code : error.code;
}

export function refusalReason(error: unknown): string | null {
    if (!(error instanceof ApiError)) return null;
    const detail = (error.payload as { detail?: unknown } | null)?.detail;
    const reason = detail && typeof detail === 'object' ? (detail as { reason?: unknown }).reason : null;
    return typeof reason === 'string' && reason.trim() ? reason.trim() : null;
}

/* did not answer */
export function problemText(error: unknown, t: (key: string) => string): string {
    const code = refusalCode(error);
    const reason = refusalReason(error);
    let words = errorText(error);
    if (code) {
        const key = `messaging.ui.error.${code}`;
        if (t(key) !== key) words = t(key);
    }
    return reason && !words.includes(reason) ? `${words} (${reason})` : words;
}

export function refresh(): Promise<void> {
    inflight ??= read().finally(() => { inflight = null; });
    return inflight;
}

async function read(): Promise<void> {
    try {
        const [providers, conversations, bindings, messages] = await Promise.all([
            fetchProviders(fetcherInUse), fetchConversations(fetcherInUse), fetchBindings(undefined, fetcherInUse),
            fetchMessages(LOG_LIMIT, fetcherInUse),
        ]);
        Object.assign(messaging, { providers, conversations, bindings, messages, loaded: true, problem: '' });
    } catch (error) {
        messaging.problem = errorText(error);
    }
}

export function attach(fetcher?: Fetcher): () => void {
    if (fetcher) fetcherInUse = fetcher;
    attached += 1;
    if (attached === 1) stop = resourcePush().pushOrPoll(() => void refresh(), FALLBACK_MS, [TOPIC]);
    void refresh();
    return () => {
        attached -= 1;
        if (attached === 0) {
            stop?.();
            stop = null;
            fetcherInUse = undefined;
        }
    };
}
