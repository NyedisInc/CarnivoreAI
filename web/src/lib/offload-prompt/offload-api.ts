/* the vault is not reachable */
import { authFetch } from '../../opscenter/api/auth.svelte';

/* offloaded to the backup vault */
export const OFFLOADED_CODE = 'offloaded';

export interface OffloadTarget {
    sessionUuid?: string | null;
    conversationId?: string | null;
    label?: string;
}

export interface OffloadedDetails {
    conversations: string[];
    bytes: number;
    offloadedAt: number;
    pluginOn: boolean;
    unreadable: boolean;
}

export interface RestoreOutcome {
    conversation_id: string;
    status: string;
    /* could not be searched */
    path?: string;
}

const ON_DISK: readonly string[] = ['written', 'already_present', 'disk_newer'];

const seg = (value: string): string => encodeURIComponent(value);

export async function readOffloaded(target: OffloadTarget): Promise<OffloadedDetails> {
    const query = new URLSearchParams();
    if (target.sessionUuid) query.set('session_uuid', target.sessionUuid);
    if (target.conversationId) query.set('conversation_id', target.conversationId);
    const body = await authFetch<{ conversations?: string[]; bytes?: number; offloaded_at?: number; plugin_on?: boolean; unreadable?: boolean }>(`/offloaded?${query}`);
    return {
        conversations: body.conversations ?? [],
        bytes: body.bytes ?? 0,
        offloadedAt: body.offloaded_at ?? 0,
        pluginOn: body.plugin_on === true,
        unreadable: body.unreadable === true,
    };
}

export async function restoreOffloaded(target: OffloadTarget): Promise<RestoreOutcome[]> {
    const path = target.sessionUuid
        ? `/cplugs/save/offload/sessions/${seg(target.sessionUuid)}/restore`
        : `/cplugs/save/offload/conversations/${seg(target.conversationId ?? '')}/restore`;
    const body = await authFetch<{ conversations?: RestoreOutcome[] }>(path, { method: 'POST', body: JSON.stringify({}) });
    return body.conversations ?? [];
}

export function firstNotRestored(outcomes: readonly RestoreOutcome[]): RestoreOutcome | null {
    return outcomes.find((o) => !ON_DISK.includes(o.status)) ?? null;
}

export function restoreAllowed(details: OffloadedDetails | null): boolean {
    return details === null || (details.pluginOn && !details.unreadable);
}
