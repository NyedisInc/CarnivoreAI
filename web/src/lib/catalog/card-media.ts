import { accessToken, auth, hasRefreshToken, refreshTokens } from '../../opscenter/api/auth.svelte';

const cache = new Map<string, Promise<string | null>>();

async function fetchBlob(sha: string, retrying = false): Promise<Blob> {
    if (auth.state === 'signed-out') throw new Error('not signed in');
    const token = accessToken();
    const headers = new Headers();
    if (token) headers.set('Authorization', `Bearer ${token}`);
    const response = await fetch(`/api/v1/catalog/media/${encodeURIComponent(sha)}`, { headers });
    if (response.status === 401) {
        if (!retrying && hasRefreshToken() && (await refreshTokens())) return fetchBlob(sha, true);
        throw new Error('not signed in');
    }
    if (!response.ok) throw new Error(`catalog media answered ${response.status}`);
    return response.blob();
}

export function catalogMediaUrl(sha: string): Promise<string | null> {
    let held = cache.get(sha);
    if (!held) {
        held = fetchBlob(sha).then(
            (blob) => URL.createObjectURL(blob),
            () => null,
        );
        cache.set(sha, held);
    }
    return held;
}
