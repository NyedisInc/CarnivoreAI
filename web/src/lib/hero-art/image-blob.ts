import { API_BASE, auth, authFetchBlob } from '../../opscenter/api/auth.svelte';

const cache = new Map<string, Promise<string | null>>();

function fetchBlob(url: string): Promise<Blob> {
    if (auth.state === 'signed-out') return Promise.reject(new Error('not signed in'));
    return authFetchBlob(url.startsWith(API_BASE) ? url.slice(API_BASE.length) : url);
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
