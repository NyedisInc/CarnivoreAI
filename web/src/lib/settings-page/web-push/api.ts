import { authFetch } from '../../../opscenter/api/auth.svelte';

export type Fetcher = typeof authFetch;

export interface PushSubscriptionRow {
    readonly id: string;
    readonly service: string;
    readonly device_id: string | null;
    readonly created_at: string | null;
    readonly last_result: { readonly status: number; readonly at: string } | null;
}

export interface PushEnvironment {
    readonly supported: boolean;
    readonly standalone: boolean;
}

export function pushEnvironment(): PushEnvironment {
    const supported =
        typeof window !== 'undefined' && 'PushManager' in window && 'serviceWorker' in navigator && 'Notification' in window;
    const standalone =
        typeof window !== 'undefined' &&
        (window.matchMedia?.('(display-mode: standalone)').matches === true ||
            (navigator as Navigator & { standalone?: boolean }).standalone === true);
    return { supported, standalone };
}

export function keyBytes(text: string): Uint8Array<ArrayBuffer> {
    const padded = text.replace(/-/g, '+').replace(/_/g, '/').padEnd(Math.ceil(text.length / 4) * 4, '=');
    const raw = atob(padded);
    return Uint8Array.from(raw, (c) => c.charCodeAt(0));
}

export async function listSubscriptions(fetcher: Fetcher = authFetch): Promise<PushSubscriptionRow[]> {
    const reply = await fetcher<{ subscriptions: PushSubscriptionRow[] }>('/push/subscriptions');
    return Array.isArray(reply?.subscriptions) ? reply.subscriptions : [];
}

export async function removeSubscription(id: string, fetcher: Fetcher = authFetch): Promise<void> {
    await fetcher<unknown>(`/push/subscriptions/${encodeURIComponent(id)}`, { method: 'DELETE' });
}

export async function sendTest(fetcher: Fetcher = authFetch): Promise<number> {
    const reply = await fetcher<{ sent: unknown[] }>('/push/test', { method: 'POST' });
    return Array.isArray(reply?.sent) ? reply.sent.length : 0;
}

export async function enableAlerts(fetcher: Fetcher = authFetch): Promise<void> {
    if ((await Notification.requestPermission()) !== 'granted') throw new Error('denied');
    await navigator.serviceWorker.register('/sw.js');
    const registration = await navigator.serviceWorker.ready;
    const { key } = await fetcher<{ key: string }>('/push/vapid-public-key');
    const subscription = await registration.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: keyBytes(key),
    });
    await fetcher<unknown>('/push/subscriptions', { method: 'POST', body: JSON.stringify(subscription.toJSON()) });
}
