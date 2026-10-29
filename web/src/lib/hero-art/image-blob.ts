import { accessToken, auth, hasRefreshToken, refreshTokens } from '../../opscenter/api/auth.svelte';

const cache = new Map<string, Promise<string | null>>();

async function fetchBlob(url: string, retrying = false): Promise<Blob> {
    if (auth.state === 'signed-out') throw new Error('not signed in');
    const token = accessToken();
    const headers = new Headers();
    if (token) headers.set('Authorization', `Bearer ${token}`);
    const response = await fetch(url, { headers });
    if (response.status === 401) {
        if (!retrying && hasRefreshToken() && (await refreshTokens())) return fetchBlob(url, true);
        throw new Error('not signed in');
    }
    if (!response.ok) throw new Error(`image answered ${response.status}`);
    return response.blob();
}

export function heroImageObjectUrl(url: string): Promise<string | null> {
    let held = cache.get(url);
    if (!held) {
        held = fetchBlob(url).then(
            (blob) => URL.createObjectURL(blob),
            () => {
                cache.delete(url);
                return null;
            },
        );
        cache.set(url, held);
    }
    return held;
}
