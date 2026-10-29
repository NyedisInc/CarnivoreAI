import { authFetch } from '../../opscenter/api/auth.svelte';
import { downloadJson } from '../manager-frame/download';

export async function exportTheme(
    id: string,
    fetcher: typeof authFetch = authFetch,
    save: (filename: string, document: unknown) => string = downloadJson,
): Promise<string> {
    const document = await fetcher<unknown>(`/themes/${encodeURIComponent(id)}/export`);
    return save(`${id}.theme.json`, document);
}
