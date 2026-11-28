import { authFetch } from '../../opscenter/api/auth.svelte';
import { inNativeShell, postToNative } from './shell';

export type Fetcher = typeof authFetch;

export const STATUS_KEY_FLAG = 'carnivore.linkstatus.key.v1';

function flagged(): boolean {
    try {
        return localStorage.getItem(STATUS_KEY_FLAG) === '1';
    } catch {
        return false;
    }
}

export async function deliverStatusKey(fetcher: Fetcher = authFetch): Promise<boolean> {
    if (!inNativeShell() || flagged()) return false;
    try {
        const reply = await fetcher<{ token?: unknown }>('/link-status/key', { method: 'POST' });
        if (typeof reply?.token !== 'string' || !postToNative({ type: 'statusKey', token: reply.token })) return false;
    } catch {
        return false;
    }
    try {
        localStorage.setItem(STATUS_KEY_FLAG, '1');
    } catch {
    }
    return true;
}
