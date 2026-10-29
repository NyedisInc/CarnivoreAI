import { authFetch } from '../../opscenter/api/auth.svelte';
import type { FeatureCatalogPayload } from './features-by-area';

let pending: Promise<FeatureCatalogPayload> | null = null;

export function loadFeatureCatalog(fetcher: typeof authFetch = authFetch): Promise<FeatureCatalogPayload> {
  pending ??= fetcher<FeatureCatalogPayload>('/feature-catalog').catch((error: unknown) => {
    pending = null;
    throw error;
  });
  return pending;
}

export function resetFeatureCatalog(): void {
  pending = null;
}
