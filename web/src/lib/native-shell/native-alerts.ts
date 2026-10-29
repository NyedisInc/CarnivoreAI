import { authFetch } from '../../opscenter/api/auth.svelte';
import { onNativeMessage, postToNative } from './shell';

export type Fetcher = typeof authFetch;

export interface NativeDeviceRow {
    readonly id: string;
    readonly platform: string;
    readonly environment: string;
    readonly device_id: string | null;
    readonly created_at: string | null;
    readonly last_result: { readonly status: number; readonly at: string } | null;
}

export const REGISTER_TIMEOUT_MS = 120_000;

export async function listNativeDevices(fetcher: Fetcher = authFetch): Promise<NativeDeviceRow[]> {
    const reply = await fetcher<{ devices: NativeDeviceRow[] }>('/native-devices');
    return Array.isArray(reply?.devices) ? reply.devices : [];
}

export async function removeNativeDevice(id: string, fetcher: Fetcher = authFetch): Promise<void> {
    await fetcher<unknown>(`/native-devices/${encodeURIComponent(id)}`, { method: 'DELETE' });
}

export async function enableNativeAlerts(fetcher: Fetcher = authFetch, timeoutMs = REGISTER_TIMEOUT_MS): Promise<string> {
    const answer = new Promise<Record<string, string>>((resolve, reject) => {
        const timer = setTimeout(() => {
            off();
            reject(new Error('timeout'));
        }, timeoutMs);
        const off = onNativeMessage((m) => {
            if (m.type !== 'pushToken' && m.type !== 'pushFailed') return;
            clearTimeout(timer);
            off();
            if (m.type === 'pushFailed') reject(new Error(m.reason));
            else resolve(m as unknown as Record<string, string>);
        });
    });
    if (!postToNative({ type: 'registerPush' })) throw new Error('no shell');
    const m = await answer;
    const row = await fetcher<{ id: string }>('/native-devices', {
        method: 'POST',
        body: JSON.stringify({
            platform: 'ios',
            token: m.token,
            environment: m.environment,
            bundle_id: m.bundle_id,
            app_version: m.app_version,
            payload_key: m.payload_key,
        }),
    });
    postToNative({ type: 'pushRegistered', id: row.id });
    return row.id;
}
