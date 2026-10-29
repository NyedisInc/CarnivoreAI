import { ApiError, authFetch } from '../../opscenter/api/auth.svelte';
import { rowFromPayload, type FavoriteColor, type FavoritesRow } from './favorites-model';

export type WriteResult =
    | { kind: 'ok'; row: FavoritesRow }
    | { kind: 'stale'; row: FavoritesRow }
    | { kind: 'failed'; message: string };

async function post(path: string, body: Record<string, unknown>): Promise<WriteResult> {
    try {
        const payload = await authFetch<unknown>(path, {
            method: 'POST',
            body: JSON.stringify(body),
        });
        return { kind: 'ok', row: rowFromPayload(payload) };
    } catch (error) {
        if (error instanceof ApiError && error.status === 409) {
            const detail = (error.payload as { detail?: { current?: unknown } } | null)?.detail;
            if (detail && typeof detail === 'object' && detail.current !== undefined) {
                return { kind: 'stale', row: rowFromPayload(detail.current) };
            }
        }
        return { kind: 'failed', message: error instanceof Error ? error.message : String(error) };
    }
}

export function setFavoriteColor(command: string, color: FavoriteColor | null): Promise<WriteResult> {
    return post('/config/common-commands/color', { command, color });
}

export function reorderFavorites(commands: string[]): Promise<WriteResult> {
    return post('/config/common-commands/order', { commands });
}

export function unstarFavorite(command: string): Promise<WriteResult> {
    return post('/config/common-commands/favorite', { command, favorite: false });
}
