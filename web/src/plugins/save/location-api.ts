import { ApiError, authFetch } from '../sdk';

const ROUTE = '/cplugs/save';
export const LOCATION_SETTING = 'vaultLocation';

export type Fetcher = typeof authFetch;

export interface LocationWarning {
    readonly code: string;
    readonly message: string;
    readonly field?: string;
    readonly detail?: string;
}

export interface LocationView {
    readonly location: string;
    readonly root: string;
    readonly available: boolean;
    readonly error: string;
    readonly refusals: readonly string[];
    readonly warnings: readonly LocationWarning[];
}

export interface LocationSaved {
    readonly warnings: readonly LocationWarning[];
}

export async function fetchLocation(fetcher: Fetcher = authFetch): Promise<LocationView> {
    const view = await fetcher<LocationView>(`${ROUTE}/location`);
    if (!view || typeof view.root !== 'string' || typeof view.available !== 'boolean') {
        throw new Error('conversation backups did not answer with a location');
    }
    return { ...view, refusals: view.refusals ?? [], warnings: view.warnings ?? [], error: view.error ?? '' };
}

export async function saveLocation(value: string, fetcher: Fetcher = authFetch): Promise<LocationSaved> {
    for (let attempt = 0; ; attempt += 1) {
        const current = await fetcher<{ revision?: number }>(ROUTE);
        try {
            const row = await fetcher<{ settings_warnings?: readonly LocationWarning[] }>(ROUTE, {
                method: 'PUT',
                body: JSON.stringify({ revision: current.revision ?? 0, settings: { [LOCATION_SETTING]: value.trim() } }),
            });
            return { warnings: row.settings_warnings ?? [] };
        } catch (error) {
            if (attempt >= 1 || !(error instanceof ApiError) || error.status !== 409) throw error;
        }
    }
}
