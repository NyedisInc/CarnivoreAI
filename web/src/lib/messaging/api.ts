import { authFetch } from '../../opscenter/api/auth.svelte';

export type Fetcher = typeof authFetch;

export type Direction = 'in' | 'out' | 'both';

export interface Provider {
    readonly id: string;
    readonly name: string;
    readonly owner_label: string;
    readonly enabled: boolean;
    readonly allow_private: boolean;
    readonly allow_plain_http: boolean;
    readonly capabilities: Readonly<Record<string, unknown>>;
    readonly idempotency: { readonly proven: boolean; readonly last_proven_at: number | null };
    readonly stream: {
        readonly state: string | null;
        readonly cursor: number;
        readonly gap: { readonly after: number; readonly oldest: number; readonly at: number } | null;
        readonly last_event_at: number | null;
        readonly last_inbound_at: number | null;
        readonly last_outbound_at: number | null;
        readonly bridge: { readonly latest: number; readonly seen_at: number } | null;
        readonly flow: 'flowing' | 'stale';
    };
    readonly secrets: Readonly<Record<string, { readonly set: boolean; readonly count?: number }>>;
}

export interface Conversation {
    readonly id: string;
    readonly provider_id: string;
    readonly label: string;
}

export interface ProviderConversation {
    readonly conversation: string;
    readonly label: string;
    readonly routable: boolean;
}

export interface Binding {
    readonly id: string;
    readonly conversation_id: string;
    readonly session_uuid: string;
    readonly session_name: string | null;
    readonly direction: Direction;
    readonly default: boolean;
    readonly held_notice: boolean;
    readonly held: number;
}

export interface Message {
    readonly id: string;
    readonly binding_id: string;
    readonly session_uuid: string | null;
    readonly direction: 'in' | 'out';
    readonly kind: string;
    readonly text: string;
    readonly status: string;
    readonly reason: string | null;
    readonly received_at: number;
}

export interface ProviderBody {
    name: string;
    base_url: string;
    token?: string;
    token_ref?: string;
    owner_senders: string[];
    owner_label?: string;
    allow_private?: boolean;
    allow_plain_http?: boolean;
}

const BASE = '/messaging';
const json = (body: unknown): string => JSON.stringify(body);
const seg = (id: string): string => encodeURIComponent(id);
const list = <T>(value: unknown): T[] => (Array.isArray(value) ? (value as T[]) : []);

export async function fetchProviders(fetcher: Fetcher = authFetch): Promise<Provider[]> {
    return list<Provider>((await fetcher<{ providers?: unknown } | null>(`${BASE}/providers`))?.providers);
}

export async function fetchConversations(fetcher: Fetcher = authFetch): Promise<Conversation[]> {
    return list<Conversation>((await fetcher<{ conversations?: unknown } | null>(`${BASE}/conversations`))?.conversations);
}

export async function fetchBindings(sessionUuid?: string, fetcher: Fetcher = authFetch): Promise<Binding[]> {
    const query = sessionUuid ? `?session_uuid=${seg(sessionUuid)}` : '';
    return list<Binding>((await fetcher<{ bindings?: unknown } | null>(`${BASE}/bindings${query}`))?.bindings);
}

export async function fetchMessages(limit = 50, fetcher: Fetcher = authFetch): Promise<Message[]> {
    return list<Message>((await fetcher<{ messages?: unknown } | null>(`${BASE}/messages?limit=${limit}`))?.messages);
}

export async function fetchProviderConversations(providerId: string, fetcher: Fetcher = authFetch): Promise<ProviderConversation[]> {
    const body = await fetcher<{ conversations?: unknown } | null>(`${BASE}/providers/${seg(providerId)}/conversations`);
    return list<ProviderConversation>(body?.conversations);
}

export const createProvider = (body: ProviderBody, fetcher: Fetcher = authFetch) =>
    fetcher<Provider>(`${BASE}/providers`, { method: 'POST', body: json(body) });

export const setProviderEnabled = (id: string, enabled: boolean, fetcher: Fetcher = authFetch) =>
    fetcher<Provider>(`${BASE}/providers/${seg(id)}`, { method: 'PATCH', body: json({ enabled }) });

export const deleteProvider = (id: string, fetcher: Fetcher = authFetch) =>
    fetcher<unknown>(`${BASE}/providers/${seg(id)}`, { method: 'DELETE' });

export const testProvider = (id: string, conversationId: string, fetcher: Fetcher = authFetch) =>
    fetcher<{ sent: boolean }>(`${BASE}/providers/${seg(id)}/test`, { method: 'POST', body: json({ conversation_id: conversationId }) });

export const createConversation = (providerId: string, conversation: string, label: string, fetcher: Fetcher = authFetch) =>
    fetcher<Conversation>(`${BASE}/conversations`, { method: 'POST', body: json({ provider_id: providerId, conversation, label }) });

export const deleteConversation = (id: string, fetcher: Fetcher = authFetch) =>
    fetcher<unknown>(`${BASE}/conversations/${seg(id)}`, { method: 'DELETE' });

export const createBinding = (conversationId: string, sessionUuid: string, direction: Direction, isDefault: boolean, fetcher: Fetcher = authFetch) =>
    fetcher<Binding>(`${BASE}/bindings`, {
        method: 'POST', body: json({ conversation_id: conversationId, session_uuid: sessionUuid, direction, default: isDefault }),
    });

export const patchBinding = (id: string, body: { direction?: Direction; default?: boolean; held_notice?: boolean }, fetcher: Fetcher = authFetch) =>
    fetcher<Binding>(`${BASE}/bindings/${seg(id)}`, { method: 'PATCH', body: json(body) });

export const deleteBinding = (id: string, fetcher: Fetcher = authFetch) =>
    fetcher<unknown>(`${BASE}/bindings/${seg(id)}`, { method: 'DELETE' });

export const retryMessage = (id: string, fetcher: Fetcher = authFetch) =>
    fetcher<Message>(`${BASE}/messages/${seg(id)}/retry`, { method: 'POST' });
