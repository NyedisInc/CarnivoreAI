import { ApiError, authFetch } from '../sdk';

const PLUGIN_ROUTE = '/cplugs/save';

export type Fetcher = typeof authFetch;

export async function savePluginSettings(change: (stored: Record<string, unknown>) => Record<string, unknown>, fetcher: Fetcher = authFetch): Promise<void> {
    for (let attempt = 0; ; attempt += 1) {
        const current = await fetcher<{ revision?: number; settings?: Record<string, unknown> }>(PLUGIN_ROUTE);
        try {
            await fetcher(PLUGIN_ROUTE, { method: 'PUT', body: JSON.stringify({ revision: current.revision ?? 0, settings: change(current.settings ?? {}) }) });
            return;
        } catch (error) {
            if (attempt >= 1 || !(error instanceof ApiError) || error.status !== 409) throw error;
        }
    }
}
