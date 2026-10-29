import { authFetch } from '../../../opscenter/api/auth.svelte';
import { deviceKey, deviceLabel } from './device-key';

export type Fetcher = typeof authFetch;

export type MuteScope = 'here' | 'everywhere';

export interface DeviceMutes {
    readonly label: string;
    readonly types: readonly string[];
}

export interface Mutes {
    readonly device: string | null;
    readonly everywhere: readonly string[];
    readonly here: readonly string[];
    readonly devices: Readonly<Record<string, DeviceMutes>>;
}

export async function getMutes(fetcher: Fetcher = authFetch): Promise<Mutes> {
    const device = deviceKey();
    return fetcher<Mutes>(`/notifications/mutes${device ? `?device=${encodeURIComponent(device)}` : ''}`);
}

export async function setMute(typeId: string, scope: MuteScope, muted: boolean, fetcher: Fetcher = authFetch,
                              device: string | null = deviceKey()): Promise<Mutes> {
    const body: Record<string, unknown> = { type_id: typeId, scope, muted };
    if (device) body.device = device;
    if (scope === 'here') body.label = deviceLabel();
    return fetcher<Mutes>('/notifications/mutes', { method: 'PUT', body: JSON.stringify(body) });
}
